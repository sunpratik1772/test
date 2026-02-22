"""FX-FRO Surveillance — ADK multi-agent pipeline."""

import datetime
import json
import logging
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.apps.app import App
from google.adk.events import Event, EventActions
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from google.genai import types as genai_types
from pydantic import BaseModel, Field

from .config import config
from .data_loaders import BASE_WORKFLOW
from .sop_guidelines import COMMS_KEYWORDS_DEFAULT, FRO_SOP
from .tools import (
    search_comms,
    search_market_data,
    search_orders,
    search_trades,
    write_attempt_artifacts,
)

# ---------------------------------------------------------------------------
# Extract parameters from the constant base YAML (read-only)
# ---------------------------------------------------------------------------
_steps_by_name: dict = {
    s["name"]: s for s in BASE_WORKFLOW.get("steps", [])
}
_orders_params: dict  = _steps_by_name.get("orders_investigation",  {}).get("parameters", {})
_trades_params: dict  = _steps_by_name.get("trades_investigation",  {}).get("parameters", {})
_market_params: dict  = _steps_by_name.get("market_data_investigation", {}).get("parameters", {})
_comms_params: dict   = _steps_by_name.get("comms_investigation",   {}).get("parameters", {})
_thresholds: dict     = BASE_WORKFLOW.get("thresholds", {})
_weights: dict        = BASE_WORKFLOW.get("scoring_weights", {})
_param_ranges: dict   = BASE_WORKFLOW.get("parameter_ranges", {})

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured Output Models
# ---------------------------------------------------------------------------


class EscalationScore(BaseModel):
    """Escalation evaluation output from the escalation_evaluator agent."""

    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall escalation score from 0.0 (no concern) to 1.0 (definite escalation).",
    )
    reasoning: str = Field(
        description="Detailed explanation of the score, citing specific findings.",
    )
    follow_up_queries: list[str] | None = Field(
        default=None,
        description="Follow-up investigation steps if score < 0.80 and more work is needed.",
    )


class PlanGoal(BaseModel):
    """One investigation goal in the FX-FRO plan."""

    step: int = Field(description="Step number 1–5.")
    tag: str = Field(description="One of: ORDERS, TRADES, MARKET, COMMS, SYNTHESIS.")
    action: str = Field(description="Opening verb: Analyze, Identify, Review, Examine, Compute.")
    description: str = Field(description="Specific goal detail for this step.")


class InvestigationPlan(BaseModel):
    """Structured investigation plan output from fx_plan_generator."""

    entity_id: str = Field(description="Trader or desk ID from the alert.")
    symbol: str = Field(description="Currency pair, e.g. GBP/USD.")
    time_window: str = Field(description="Date and time range, e.g. 09:00-09:30 on 2024-01-15.")
    investigation_goals: list[PlanGoal] = Field(
        description="Exactly 5 investigation goals in step order.",
    )
    prose: str = Field(
        description=(
            "The same 5 goals as a numbered markdown list. Each line: "
            "'N. **Action** description [TAG]: detail.' Use \\n between items."
        ),
    )


# ---------------------------------------------------------------------------
# FunctionTool wrappers
# ---------------------------------------------------------------------------

search_orders_tool = FunctionTool(search_orders)
search_trades_tool = FunctionTool(search_trades)
search_market_data_tool = FunctionTool(search_market_data)
search_comms_tool = FunctionTool(search_comms)
write_attempt_artifacts_tool = FunctionTool(write_attempt_artifacts)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


def _smart_merge(existing: dict, data: dict) -> None:
    """Merge data into existing, never downgrading a list-of-dicts to list-of-non-dicts."""
    for key, val in data.items():
        if (
            key in existing
            and isinstance(existing[key], list) and existing[key]
            and isinstance(existing[key][0], dict)
            and isinstance(val, list) and (not val or not isinstance(val[0], dict))
        ):
            continue  # keep the richer (dict-based) version
        existing[key] = val


def initialize_workflow_callback(callback_context: CallbackContext) -> None:
    """Seed active_workflow from BASE_WORKFLOW at the start of each session."""
    state = callback_context.state
    if not state.get("active_workflow"):
        import copy
        state["active_workflow"] = copy.deepcopy(BASE_WORKFLOW)


def collect_evidence_callback(callback_context: CallbackContext) -> None:
    """Accumulate investigator findings into session state."""
    state = callback_context.state
    existing = state.get("surveillance_findings", {})
    if isinstance(existing, str):
        try:
            existing = json.loads(existing)
        except (json.JSONDecodeError, ValueError):
            existing = {}
    if not isinstance(existing, dict):
        existing = {}
    session = callback_context._invocation_context.session

    for event in session.events:
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            data: dict | None = None

            # 1. Read raw tool outputs from function responses (list-of-dicts preserved)
            if hasattr(part, "function_response") and part.function_response:
                resp = part.function_response.response
                if isinstance(resp, dict):
                    # ADK wraps in {"result": ...} or returns directly
                    inner = resp.get("result", resp)
                    if isinstance(inner, dict):
                        data = inner

            # 2. Read LLM text JSON summaries
            elif part.text:
                text = part.text.strip()
                if text.startswith("{"):
                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, dict):
                            data = parsed
                    except (json.JSONDecodeError, ValueError):
                        pass

            if data:
                _smart_merge(existing, data)

    state["surveillance_findings"] = existing

    # Feed refined_workflow parameters back into active_workflow for next iteration
    refined = existing.get("refined_workflow", {})
    if isinstance(refined, dict) and refined:
        active = state.get("active_workflow")
        if isinstance(active, dict):
            import copy
            active = copy.deepcopy(active)
            thresholds = active.setdefault("thresholds", {})
            # Map refined_workflow output keys → active_workflow threshold keys
            _refinement_map = {
                "cancel_rate_threshold_used": "spoofing_cancel_rate",
                "front_run_seconds_used":     "front_running_seconds",
                "wash_trade_seconds_used":    "wash_trade_seconds",
            }
            for refined_key, yaml_key in _refinement_map.items():
                if refined_key in refined and refined[refined_key] is not None:
                    thresholds[yaml_key] = refined[refined_key]
            # Also store the expanded time window for context
            if refined.get("time_window_expanded"):
                active["last_time_window_expanded"] = refined["time_window_expanded"]
            if refined.get("expansion_rules_fired"):
                active["last_expansion_rules_fired"] = refined["expansion_rules_fired"]
            state["active_workflow"] = active


def evidence_folder_callback(
    callback_context: CallbackContext,
) -> genai_types.Content:
    """Write attempt artifacts to agent_outputs/attempt_N/ after each cycle."""
    state = callback_context.state
    current_attempt: int = state.get("current_attempt", 1)
    escalation_score_data = state.get("escalation_score_data", {})
    if isinstance(escalation_score_data, str):
        try:
            escalation_score_data = json.loads(escalation_score_data)
        except (json.JSONDecodeError, ValueError):
            escalation_score_data = {}
    raw_findings = state.get("surveillance_findings", {})
    if isinstance(raw_findings, str):
        try:
            raw_findings = json.loads(raw_findings)
        except (json.JSONDecodeError, ValueError):
            raw_findings = {}
    findings: dict = dict(raw_findings) if isinstance(raw_findings, dict) else {}

    if isinstance(escalation_score_data, dict):
        findings["escalation_score"] = escalation_score_data.get("score", 0.0)
        findings["reasoning"] = escalation_score_data.get("reasoning", "")
        findings["follow_up_queries"] = escalation_score_data.get("follow_up_queries") or []

    # Backfill detailed record arrays for Excel if LLM omitted or truncated them
    _entity = findings.get("entity_id", "")
    _tw = findings.get("time_window", "")
    _symbol = findings.get("symbol", "EUR/USD")
    if _entity and _tw:
        if not findings.get("filtered_orders"):
            try:
                findings["filtered_orders"] = search_orders(_entity, _tw).get("filtered_orders", [])
            except Exception:
                pass
        if not findings.get("filtered_trades"):
            try:
                findings["filtered_trades"] = search_trades(_entity, _tw).get("filtered_trades", [])
            except Exception:
                pass
        if not findings.get("market_data_snapshot"):
            try:
                findings["market_data_snapshot"] = search_market_data(_symbol, _tw).get("market_data_snapshot", [])
            except Exception:
                pass
        if not findings.get("hit_details"):
            try:
                findings["hit_details"] = search_comms(_entity, _tw).get("hit_details", [])
            except Exception:
                pass

    refined_workflow: dict = findings.pop("refined_workflow", {})

    try:
        paths = write_attempt_artifacts(
            attempt_n=current_attempt,
            findings=findings,
            refined_workflow=refined_workflow,
        )
        logger.info(
            f"Attempt {current_attempt} artifacts written: "
            f"yaml={paths['yaml_path']} score={findings.get('escalation_score', 0.0):.2f}"
        )
        state["last_artifact_paths"] = paths

        yaml_content = ""
        closure_content = ""
        try:
            with open(paths["yaml_path"]) as f:
                yaml_content = f.read()
        except Exception:
            pass
        try:
            with open(paths["closure_path"]) as f:
                closure_content = f.read()
        except Exception:
            pass

        payload = json.dumps({
            "__type": "artifact_written",
            "attempt_n": current_attempt,
            "score": findings.get("escalation_score", 0.0),
            "decision": (
                "ESCALATE" if findings.get("escalation_score", 0.0) >= config.escalation_threshold
                else "INVESTIGATE_FURTHER" if findings.get("escalation_score", 0.0) >= 0.60
                else "MONITOR"
            ),
            "yaml_path": paths["yaml_path"],
            "xlsx_path": paths["xlsx_path"],
            "closure_path": paths["closure_path"],
            "yaml_content": yaml_content,
            "closure_content": closure_content,
            "sop_sections_invoked": refined_workflow.get("sop_sections_invoked", []),
            "time_window_base": refined_workflow.get("time_window_base", ""),
            "time_window_expanded": refined_workflow.get("time_window_expanded", ""),
            "expansion_rules_fired": refined_workflow.get("expansion_rules_fired", []),
        })
    except Exception as exc:
        payload = json.dumps({
            "__type": "artifact_written",
            "attempt_n": current_attempt,
            "score": 0.0,
            "error": str(exc),
        })
        logger.warning(f"Could not write attempt {current_attempt} artifacts: {exc}")

    return genai_types.Content(parts=[genai_types.Part(text=payload)])


# ---------------------------------------------------------------------------
# Custom BaseAgent — EscalationChecker
# ---------------------------------------------------------------------------


class EscalationChecker(BaseAgent):
    """Exits the investigation loop when escalation score reaches threshold."""

    def __init__(self, name: str) -> None:
        super().__init__(name=name)

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        score_data = ctx.session.state.get("escalation_score_data", {})
        score = score_data.get("score", 0.0) if isinstance(score_data, dict) else 0.0

        current_attempt: int = ctx.session.state.get("current_attempt", 1)
        ctx.session.state["current_attempt"] = current_attempt + 1

        escalating = score >= config.escalation_threshold
        logger.info(
            f"[{self.name}] Attempt {current_attempt} | Score {score:.2f} | "
            f"{'ESCALATING' if escalating else 'CONTINUING'}"
        )

        payload = json.dumps({
            "__type": "escalation_check",
            "attempt": current_attempt,
            "score": round(score, 4),
            "threshold": config.escalation_threshold,
            "decision": "ESCALATE" if escalating else "CONTINUE",
        })

        if escalating:
            yield Event(
                author=self.name,
                content=genai_types.Content(parts=[genai_types.Part(text=payload)]),
                actions=EventActions(escalate=True),
            )
        else:
            yield Event(
                author=self.name,
                content=genai_types.Content(parts=[genai_types.Part(text=payload)]),
            )


# ---------------------------------------------------------------------------
# fx_plan_generator
# ---------------------------------------------------------------------------

fx_plan_generator = LlmAgent(
    model=config.worker_model,
    name="fx_plan_generator",
    description="Generates or refines an FX-FRO surveillance investigation plan.",
    # output_schema removed — frontend parses prose directly via regex
    instruction=f"""
    You are an FX surveillance strategist. Create a structured INVESTIGATION PLAN
    for an FX front-running-order (FX-FRO) alert.

    BASE WORKFLOW (from fx_fro_surveillance.yaml):
    - Step 1 [ORDERS]    : Detect spoofing (cancel rate >70%) and layering
    - Step 2 [TRADES]    : Detect wash trades and front-running (<60s client→prop)
    - Step 3 [MARKET]    : Check price impact and volume anomalies
    - Step 4 [COMMS]     : Search for coordination keywords in communications
    - Step 5 [SYNTHESIS] : Compute weighted escalation score from all findings

    EXISTING PLAN (if any): {{surveillance_plan?}}

    RULES:
    - investigation_goals must have exactly 5 entries, one per step above, in order.
    - Each goal's tag must be one of: ORDERS, TRADES, MARKET, COMMS, SYNTHESIS.
    - The prose field must be the same 5 goals as a numbered markdown list.
      Each line format: "N. **Action** detail [TAG]: elaboration."
      Example: "1. **Analyze** JONES_R order submissions [ORDERS]: Look for cancel rates >70%..."
    - When the analyst asks to refine or adjust, update BOTH investigation_goals AND prose consistently.
    - Do NOT perform any investigation yourself. Just plan.
    Current date: {datetime.datetime.now().strftime("%Y-%m-%d")}
    """,
)


# ---------------------------------------------------------------------------
# Single Data Investigator (replaces 4 parallel agents — saves 3 LLM calls)
# ---------------------------------------------------------------------------

data_investigator = LlmAgent(
    model=config.worker_model,
    name="data_investigator",
    description="Runs all four data investigations sequentially using base YAML parameters.",
    instruction=f"""
    You are a senior FX surveillance analyst running the RULES-BASED investigation phase.
    You must call ALL FOUR search tools in sequence using the exact base YAML parameters below.
    Do NOT skip any tool. Do NOT change the parameters.

    BASE YAML PARAMETERS:
    Orders:
      lookback_minutes      : {_orders_params.get('lookback_minutes', 60)}
      cancel_rate_threshold : {_orders_params.get('cancel_rate_threshold', 0.70)}
      anomaly_threshold     : {_orders_params.get('anomaly_threshold', 0.65)}

    Trades:
      lookback_minutes      : {_trades_params.get('lookback_minutes', 60)}
      front_run_seconds     : {_trades_params.get('front_run_seconds', 60)}
      wash_trade_seconds    : {_trades_params.get('wash_trade_seconds', 300)}

    Market Data:
      lookback_minutes      : {_market_params.get('lookback_minutes', 60)}
      impact_window_minutes : {_market_params.get('impact_window_minutes', 10)}
      volume_zscore_threshold: {_market_params.get('volume_zscore_threshold', 2.0)}

    Comms:
      lookback_minutes      : {_comms_params.get('lookback_minutes', 90)}

    PROCEDURE:
    1. Extract entity_id, symbol, and time_window from 'surveillance_plan' or the alert message.
       Default symbol: 'EUR/USD'. Default entity_id: extract from the alert.
    2. Call search_orders(entity_id, time_window) — detect spoofing and layering.
    3. Call search_trades(entity_id, time_window) — detect wash trades and front-running.
    4. Call search_market_data(symbol, time_window) — detect price/volume anomalies.
    5. Call search_comms(entity_id, time_window) — detect coordination keywords.
    6. After ALL four tools have returned results, merge ALL tool outputs into one JSON object.
       The tools already return the correct field names — do NOT rename any fields.
       Just combine every field from all four tool responses into a single flat JSON:

    {{
      "entity_id": "<from any tool response>",
      "symbol": "<symbol>",
      "time_window": "<window>",
      "orders_anomaly_score": <from search_orders>,
      "cancel_rate": <from search_orders>,
      "spoofing_flag": <from search_orders>,
      "layering_patterns": <from search_orders>,
      "trades_anomaly_score": <from search_trades>,
      "wash_trade_pairs": <list from search_trades>,
      "front_running_signals": <list from search_trades>,
      "market_data_anomaly_score": <from search_market_data>,
      "price_change_pct": <from search_market_data>,
      "volume_zscore": <from search_market_data>,
      "volume_anomaly_flag": <from search_market_data>,
      "spread_widening_flag": <from search_market_data>,
      "comms_coordination_score": <from search_comms>,
      "keyword_hits": <from search_comms>,
      "hit_details": <from search_comms>
    }}

    Output ONLY the JSON object. No markdown. No text outside the JSON.
    Current date: {datetime.datetime.now().strftime("%Y-%m-%d")}
    """,
    tools=[search_orders_tool, search_trades_tool, search_market_data_tool, search_comms_tool],
    output_key="surveillance_findings",
    after_agent_callback=collect_evidence_callback,
)


# ---------------------------------------------------------------------------
# Escalation Evaluator
# ---------------------------------------------------------------------------

escalation_evaluator = LlmAgent(
    model=config.critic_model,
    name="escalation_evaluator",
    description="Computes overall escalation score using weights from base YAML.",
    instruction=f"""
    You are a senior FX compliance analyst computing an overall escalation score.

    Review state keys: 'surveillance_findings'.

    SCORING WEIGHTS (from fx_fro_surveillance.yaml — do not change):
      orders_anomaly      : {_weights.get('orders_anomaly', 0.25)}
      trades_anomaly      : {_weights.get('trades_anomaly', 0.35)}
      market_data_anomaly : {_weights.get('market_data_anomaly', 0.20)}
      comms_coordination  : {_weights.get('comms_coordination', 0.20)}

    ESCALATION THRESHOLD (from base YAML): {_thresholds.get('escalation', 0.80)}

    Formula:
      score = (orders_anomaly_score × {_weights.get('orders_anomaly', 0.25)})
            + (trades_anomaly_score × {_weights.get('trades_anomaly', 0.35)})
            + (market_data_anomaly_score × {_weights.get('market_data_anomaly', 0.20)})
            + (comms_coordination_score × {_weights.get('comms_coordination', 0.20)})

    Bonuses (applied after weighted score, hard cap 1.0):
      + 0.15  if front_running_signals ≥ 1
      + 0.10  if wash_trade_pairs ≥ 2
      + 0.10  if spoofing_flag = True
      + 0.05  if comms contain EVASION_LANGUAGE category hits
      − 0.05  per plausible alternative hypothesis documented

    Thresholds:
      0.00–0.30 : CLOSE
      0.31–0.59 : MONITOR
      0.60–0.79 : INVESTIGATE FURTHER (loop continues)
      0.80–1.00 : ESCALATE

    Provide detailed reasoning citing specific findings.
    If score < {_thresholds.get('escalation', 0.80)}, list concrete
    follow_up_queries per the SOP (which sections to invoke, what to expand).

    Current date: {datetime.datetime.now().strftime("%Y-%m-%d")}
    Respond with a single raw JSON matching EscalationScore schema:
    {{
      "score": <float 0.0–1.0>,
      "reasoning": "<detailed explanation citing findings>",
      "follow_up_queries": ["<SOP-guided step>", ...]
    }}
    """,
    output_schema=EscalationScore,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    output_key="escalation_score_data",
)


# ---------------------------------------------------------------------------
# Agentic Investigator (inside loop)
# ---------------------------------------------------------------------------

agentic_investigator = LlmAgent(
    model=config.worker_model,
    name="agentic_investigator",
    description="Executes a refined SOP-guided investigation cycle.",
    instruction=f"""
    You are an expert FX surveillance investigator executing an AGENTIC investigation cycle.
    You have been activated because the escalation score is below {_thresholds.get('escalation', 0.80)}.

    The BASE WORKFLOW parameters (from fx_fro_surveillance.yaml) are:
      cancel_rate_threshold : {_thresholds.get('spoofing_cancel_rate', 0.70)}
      front_run_seconds     : {_thresholds.get('front_running_seconds', 60)}
      wash_trade_seconds    : {_thresholds.get('wash_trade_seconds', 300)}
      volume_zscore         : {_thresholds.get('volume_zscore', 2.0)}
      escalation_threshold  : {_thresholds.get('escalation', 0.80)}

    You MAY refine these parameters per the SOP rules below.
    Document every refinement in your output under "refined_workflow".

    ═══════════════════════════════════════════════════════════════
    FULL STANDARD OPERATING PROCEDURE (follow this precisely):
    ═══════════════════════════════════════════════════════════════
    {FRO_SOP}
    ═══════════════════════════════════════════════════════════════

    CURRENT STATE:
    - escalation_score_data : {{escalation_score_data}}
    - current_attempt       : {{current_attempt}}
    - surveillance_findings : {{surveillance_findings}}
    - active_workflow       : {{active_workflow}}

    If active_workflow contains updated thresholds from a previous cycle
    (e.g. spoofing_cancel_rate, front_running_seconds, wash_trade_seconds),
    PREFER those values over the BASE WORKFLOW PARAMETERS listed above.
    Document any deviation in refined_workflow.

    EXECUTION STEPS:

    Step 1 — READ THE GAPS
      Read follow_up_queries from 'escalation_score_data'.

    Step 2 — APPLY SOP TIME WINDOW EXPANSION (Section 2)
      - Rule A (cancel_rate > 0.50): expand to base_start − 90 min
      - Rule B (front_running_signals > 0): expand to base_start − 120 min
      - Rule C (wash_trade_pairs ≥ 2): use full session window
      - Rule D (comms_keyword_hits ≥ 5): expand comms window − 120 min
      - Rule E (volume_zscore > 3.0): expand market window − 180 min

    Step 3 — EXECUTE TOOL CALLS WITH REFINED PARAMETERS
      Call the appropriate tools with expanded windows / refined thresholds.

    Step 4 — TRADER HISTORY (Section 7, iteration ≥ 2)
      If current_attempt ≥ 2: also search prior day for baseline.

    Step 5 — NARRATIVE SYNTHESIS (Section 8)
      Compute narrative_score (each present element = +0.20):
      (a) Pre-trade comms with client order knowledge
      (b) Prop pre-positioning before client order
      (c) Client order execution found
      (d) Prop position closed at profit after client fill
      (e) Price moved in prop trade direction

    Step 6 — ALTERNATIVE HYPOTHESES (Section 8.3)
      Document at least one alternative hypothesis.

    Step 7 — OUTPUT JSON
      Your output MUST be a single valid JSON with ALL keys:

      {{
        "entity_id": "<str>",
        "symbol": "<str>",
        "time_window": "<str>",
        "orders_anomaly_score": <float>,
        "trades_anomaly_score": <float>,
        "market_data_anomaly_score": <float>,
        "comms_coordination_score": <float>,
        "spoofing_flag": <bool>,
        "wash_trade_pairs": <int>,
        "front_running_signals": <int>,
        "comms_keyword_hits": <int>,
        "comms_categories_hit": <list>,
        "filtered_orders": <list>,
        "filtered_trades": <list>,
        "market_data_snapshot": <list>,
        "hit_details": <list>,
        "narrative_score": <float>,
        "alternative_hypotheses_considered": <list>,
        "sop_sections_invoked": <list>,
        "refined_workflow": {{
          "attempt": <int>,
          "investigation_type": "agentic",
          "base_workflow_ref": "fx_fro_surveillance.yaml",
          "sop_sections_invoked": <list>,
          "time_window_base": "<str>",
          "time_window_expanded": "<str>",
          "expansion_reason": "<str>",
          "expansion_rules_fired": <list>,
          "cancel_rate_threshold_used": <float>,
          "front_run_seconds_used": <int>,
          "wash_trade_seconds_used": <int>,
          "comms_keywords_used": <list>,
          "extra_checks_performed": <list>,
          "findings_delta": {{
            "new_front_running_signals": <int>,
            "new_wash_trade_pairs": <int>,
            "new_comms_hits": <int>,
            "spoofing_flag_changed": "<str>"
          }}
        }}
      }}

    Current date: {datetime.datetime.now().strftime("%Y-%m-%d")}
    Output ONLY a valid JSON object — no markdown, no text outside the JSON.
    """,
    tools=[search_orders_tool, search_trades_tool, search_market_data_tool, search_comms_tool],
    output_key="surveillance_findings",
    after_agent_callback=collect_evidence_callback,
)


# ---------------------------------------------------------------------------
# Agentic Planner (plan-then-execute — plan step, no tools)
# ---------------------------------------------------------------------------

agentic_planner = LlmAgent(
    model=config.worker_model,
    name="agentic_planner",
    description="Generates a structured investigation plan before tool execution.",
    instruction=f"""
    You are an FX surveillance investigation PLANNER. Your ONLY job is to CREATE A PLAN.
    Do NOT call any tools. Do NOT investigate data. Just plan.

    Read the follow_up_queries from escalation_score_data, the current surveillance_findings,
    and the active_workflow thresholds. Then produce a structured investigation plan
    describing EXACTLY what the executor will do next.

    CURRENT STATE:
    - escalation_score_data : {{escalation_score_data}}
    - surveillance_findings : {{surveillance_findings}}
    - active_workflow       : {{active_workflow}}
    - current_attempt       : {{current_attempt}}

    SOP TIME WINDOW EXPANSION RULES (apply these to decide the expanded window):
    - Rule A (cancel_rate > 0.50)         : expand base_start − 90 min
    - Rule B (front_running_signals > 0)  : expand base_start − 120 min
    - Rule C (wash_trade_pairs ≥ 2)       : use full session window
    - Rule D (comms_keyword_hits ≥ 5)     : expand comms window − 120 min
    - Rule E (volume_zscore > 3.0)        : expand market window − 180 min

    PARAMETER BOUNDS (from active_workflow.parameter_ranges — stay within these):
      front_run_seconds     : [{_param_ranges.get('front_run_seconds', {}).get('min', 30)}–{_param_ranges.get('front_run_seconds', {}).get('max', 300)}]
      cancel_rate_threshold : [{_param_ranges.get('cancel_rate_threshold', {}).get('min', 0.50)}–{_param_ranges.get('cancel_rate_threshold', {}).get('max', 0.95)}]
      wash_trade_seconds    : [{_param_ranges.get('wash_trade_seconds', {}).get('min', 60)}–{_param_ranges.get('wash_trade_seconds', {}).get('max', 900)}]

    Output ONLY a valid JSON object — no markdown, no text outside JSON:
    {{
      "attempt": <int from current_attempt>,
      "entity_id": "<str>",
      "symbol": "<str>",
      "time_window": {{
        "base": "<str>",
        "expanded": "<str>",
        "expansion_reason": "<str>",
        "rules_applied": ["Rule A", "..."]
      }},
      "parameters": {{
        "cancel_rate_threshold": <float>,
        "front_run_seconds": <int>,
        "wash_trade_seconds": <int>,
        "comms_lookback_minutes": <int>
      }},
      "tools_sequence": [
        {{"tool": "search_orders",      "reason": "<why>"}},
        {{"tool": "search_trades",      "reason": "<why>"}},
        {{"tool": "search_market_data", "reason": "<why>"}},
        {{"tool": "search_comms",       "reason": "<why>"}}
      ],
      "sop_sections": ["<section names>"],
      "follow_up_queries_addressed": ["<from escalation_score_data.follow_up_queries>"]
    }}

    Current date: {datetime.datetime.now().strftime("%Y-%m-%d")}
    """,
    output_key="agentic_plan",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)


# ---------------------------------------------------------------------------
# Agentic Executor (plan-then-execute — execution step, has tools)
# ---------------------------------------------------------------------------

agentic_executor = LlmAgent(
    model=config.worker_model,
    name="agentic_executor",
    description="Executes the agentic investigation plan by calling tools with planned parameters.",
    instruction=f"""
    You are an expert FX surveillance investigator. Execute the investigation plan from state.
    You have been activated because the escalation score is below {_thresholds.get('escalation', 0.80)}.

    CURRENT STATE:
    - agentic_plan          : {{agentic_plan}}
    - surveillance_findings : {{surveillance_findings}}
    - escalation_score_data : {{escalation_score_data}}
    - active_workflow       : {{active_workflow}}

    EXECUTION RULES:
    1. Read agentic_plan carefully. Use EXACTLY the time_window.expanded as your time window.
       If agentic_plan is missing, fall back to the base parameters from active_workflow.
    2. Call search_orders with the planned cancel_rate_threshold.
    3. Call search_trades, search_market_data, search_comms.
    4. After ALL four tools return, synthesize findings.
    5. In refined_workflow, document the parameters you actually used (from the plan).

    FULL STANDARD OPERATING PROCEDURE (for narrative synthesis, Sections 7–8):
    {FRO_SOP}

    EXECUTION STEPS:

    Step 1 — READ THE PLAN
      Read agentic_plan carefully. Note the time_window.expanded, parameters, and tools_sequence.

    Step 2 — EXECUTE TOOL CALLS WITH PLAN PARAMETERS
      Call search_orders, search_trades, search_market_data, search_comms with the
      EXACT parameters from agentic_plan (expanded time window, refined thresholds).

    Step 3 — TRADER HISTORY (Section 7, iteration ≥ 2)
      If current_attempt ≥ 2: also search prior day for baseline.

    Step 4 — NARRATIVE SYNTHESIS (Section 8)
      Compute narrative_score (each present element = +0.20):
      (a) Pre-trade comms with client order knowledge
      (b) Prop pre-positioning before client order
      (c) Client order execution found
      (d) Prop position closed at profit after client fill
      (e) Price moved in prop trade direction

    Step 5 — ALTERNATIVE HYPOTHESES (Section 8.3)
      Document at least one alternative hypothesis.

    Step 6 — OUTPUT JSON
      Your output MUST be a single valid JSON with ALL keys:

      {{
        "entity_id": "<str>",
        "symbol": "<str>",
        "time_window": "<str>",
        "orders_anomaly_score": <float>,
        "trades_anomaly_score": <float>,
        "market_data_anomaly_score": <float>,
        "comms_coordination_score": <float>,
        "spoofing_flag": <bool>,
        "wash_trade_pairs": <int>,
        "front_running_signals": <int>,
        "comms_keyword_hits": <int>,
        "comms_categories_hit": <list>,
        "filtered_orders": <list>,
        "filtered_trades": <list>,
        "market_data_snapshot": <list>,
        "hit_details": <list>,
        "narrative_score": <float>,
        "alternative_hypotheses_considered": <list>,
        "sop_sections_invoked": <list>,
        "refined_workflow": {{
          "attempt": <int>,
          "investigation_type": "agentic",
          "base_workflow_ref": "fx_fro_surveillance.yaml",
          "sop_sections_invoked": <list>,
          "time_window_base": "<str>",
          "time_window_expanded": "<str>",
          "expansion_reason": "<str>",
          "expansion_rules_fired": <list>,
          "cancel_rate_threshold_used": <float>,
          "front_run_seconds_used": <int>,
          "wash_trade_seconds_used": <int>,
          "comms_keywords_used": <list>,
          "extra_checks_performed": <list>,
          "findings_delta": {{
            "new_front_running_signals": <int>,
            "new_wash_trade_pairs": <int>,
            "new_comms_hits": <int>,
            "spoofing_flag_changed": "<str>"
          }}
        }}
      }}

    Current date: {datetime.datetime.now().strftime("%Y-%m-%d")}
    Output ONLY a valid JSON object — no markdown, no text outside the JSON.
    """,
    tools=[search_orders_tool, search_trades_tool, search_market_data_tool, search_comms_tool],
    output_key="surveillance_findings",
    after_agent_callback=collect_evidence_callback,
)


# ---------------------------------------------------------------------------
# Evidence Compiler (final step)
# ---------------------------------------------------------------------------

evidence_compiler = LlmAgent(
    model=config.critic_model,
    name="evidence_compiler",
    include_contents="none",
    description="Compiles all investigation findings into a final evidence report.",
    instruction="""
    You are a compliance evidence compiler. Produce the final FX-FRO surveillance report.

    INPUT STATE KEYS:
    - 'surveillance_findings'  : all merged findings
    - 'escalation_score_data'  : final escalation score and reasoning
    - 'alert_details'          : original alert
    - 'surveillance_plan'      : approved investigation plan
    - 'last_artifact_paths'    : paths to artifact files

    PRODUCE THIS REPORT STRUCTURE:

    # FX-FRO SURVEILLANCE REPORT

    ## Executive Summary
    Entity, symbol, time window, final escalation score, decision (ESCALATE/MONITOR/CLOSE).

    ## Key Findings

    ### Front-Running Evidence
    List all front_running_signals (if any).

    ### Wash Trades
    List all wash_trade_pairs (if any).

    ### Spoofing / Layering
    Cancel rate, spoofing_flag, layering_patterns.

    ### Market Impact
    Price change %, volume Z-score, spread widening.

    ### Communications
    Keyword hits, pre-trade coordination evidence.

    ## Scoring Breakdown
    | Component | Score | Weight | Contribution |
    |---|---|---|---|
    | Orders Anomaly | ... | 25% | ... |
    | Trades Anomaly | ... | 35% | ... |
    | Market Data | ... | 20% | ... |
    | Comms | ... | 20% | ... |
    | **TOTAL** | | | **X.XX** |

    ## Recommendation
    Clear compliance action recommendation.

    ## Evidence Files
    List artifact file paths from 'last_artifact_paths'.
    """,
    output_key="final_surveillance_report",
    after_agent_callback=evidence_folder_callback,
)


# ---------------------------------------------------------------------------
# Investigation Loop
# ---------------------------------------------------------------------------

investigation_loop = LoopAgent(
    name="investigation_loop",
    max_iterations=config.max_investigation_iterations,
    sub_agents=[
        escalation_evaluator,
        EscalationChecker(name="escalation_checker"),
        agentic_planner,    # plan first — shown in UI before any tool calls
        agentic_executor,   # execute per plan
    ],
)


# ---------------------------------------------------------------------------
# Surveillance Pipeline
# ---------------------------------------------------------------------------

surveillance_pipeline = SequentialAgent(
    name="surveillance_pipeline",
    description="Full FX-FRO surveillance: data investigation, scoring loop, evidence compile.",
    sub_agents=[
        data_investigator,
        investigation_loop,
        evidence_compiler,
    ],
)


# ---------------------------------------------------------------------------
# Root Agent
# ---------------------------------------------------------------------------

workflow_initializer_agent = LlmAgent(
    name="workflow_initializer_agent",
    model=config.worker_model,
    description="Primary FX-FRO surveillance assistant. Collaborates with analyst to create "
                "an investigation plan, then executes it upon approval.",
    before_agent_callback=initialize_workflow_callback,
    instruction=f"""
    You are an FX surveillance analyst assistant investigating FX front-running-order (FX-FRO) alerts.

    CRITICAL RULE: Never answer directly. ALWAYS call fx_plan_generator first.

    WORKFLOW:
    1. PLAN   : Call fx_plan_generator to create a draft plan. Present it clearly to the analyst.
    2. REFINE : Incorporate feedback until the plan is approved.
    3. EXECUTE: On EXPLICIT approval ("run it", "looks good", "proceed", "yes", "approved"),
                store the plan in 'surveillance_plan' state and delegate to surveillance_pipeline.
    4. REPORT : Present final_surveillance_report including escalation decision and artifact paths.

    EXAMPLE ALERTS:
    - "Investigate trader SMITH_J on EUR/USD between 09:00-10:30 on 2024-01-15"
    - "Review suspicious activity for desk FX_PROP_1 on GBP/USD on 2024-01-15"

    Current date: {datetime.datetime.now().strftime("%Y-%m-%d")}
    Do not investigate yourself. Plan, Refine, Delegate.
    """,
    sub_agents=[surveillance_pipeline],
    tools=[AgentTool(fx_plan_generator)],
    output_key="surveillance_plan",
)

root_agent = workflow_initializer_agent
app = App(root_agent=root_agent, name="app")
