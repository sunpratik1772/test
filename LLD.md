# Low-Level Design (LLD) — FX Front-Running-Order (FX-FRO) Surveillance System

**Author:** Supratik Datta  
**Date:** 2026-02-22  
**Version:** 1.0  
**Repository:** fx-fro-surveillance

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Module Design](#3-module-design)
   - 3.1 [Configuration Layer (`app/config.py`)](#31-configuration-layer-appconfigpy)
   - 3.2 [Data Layer (`app/data_loaders.py`)](#32-data-layer-appdata_loaderspy)
   - 3.3 [Investigation Tools (`app/tools.py`)](#33-investigation-tools-apptoolspy)
   - 3.4 [SOP Guidelines (`app/sop_guidelines.py`)](#34-sop-guidelines-appsop_guidelinespy)
   - 3.5 [Agent Pipeline (`app/agent.py`)](#35-agent-pipeline-appagentpy)
   - 3.6 [Backend Server (`server.py`)](#36-backend-server-serverpy)
   - 3.7 [Frontend (`frontend/`)](#37-frontend-frontend)
4. [Agent Interaction Flow](#4-agent-interaction-flow)
5. [Data Schemas](#5-data-schemas)
6. [Escalation Scoring Model](#6-escalation-scoring-model)
7. [Artifact Output Specification](#7-artifact-output-specification)
8. [API Endpoints](#8-api-endpoints)
9. [State Management](#9-state-management)
10. [Key Algorithms](#10-key-algorithms)
11. [Configuration Reference](#11-configuration-reference)
12. [Error Handling & Resilience](#12-error-handling--resilience)

---

## 1. System Overview

The **FX-FRO Surveillance System** is a production-grade, AI-powered compliance investigation platform designed to detect and escalate **illegal FX trading behaviour**, including:

| Behaviour | Description |
|---|---|
| **Front-Running** | Proprietary trader places own trade ahead of a known client order |
| **Spoofing** | Placing large orders with intent to cancel, to manipulate price |
| **Layering** | Stacking multiple fictitious orders at different price levels |
| **Wash Trading** | Buying and selling with the same counterparty to create artificial volume |
| **Communication Coordination** | Pre-arranged trading coordination detected via chat/email/phone keyword scanning |

The system implements a **Human-in-the-Loop (HITL)** agentic workflow built on **Google's Agent Development Kit (ADK)** and **Gemini LLMs**, with a React frontend and a FastAPI backend.

---

## 2. High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                     React Frontend (Vite + Tailwind)               │
│     Chat UI │ Investigation Timeline │ Report Viewer │ XLSX DL     │
└─────────────────────────┬──────────────────────────────────────────┘
                          │ HTTP / Server-Sent Events (SSE)
                          │ POST /api/run_sse
                          │ GET  /api/rate-limit-status
                          │ GET  /files/<attempt_N>/data.xlsx
┌─────────────────────────▼──────────────────────────────────────────┐
│                   FastAPI Backend (server.py)                       │
│   ADK get_fast_api_app()  +  /files/ StaticFiles  +  rate-limit   │
└─────────────────────────┬──────────────────────────────────────────┘
                          │
┌─────────────────────────▼──────────────────────────────────────────┐
│           Google ADK Multi-Agent Runtime (app/agent.py)            │
│                                                                    │
│   workflow_initializer_agent  (root, HITL)                        │
│   └─► fx_plan_generator       (AgentTool)                         │
│   └─► surveillance_pipeline   (SequentialAgent)                   │
│       ├─► data_investigator   (LlmAgent + 4 tools)                │
│       ├─► investigation_loop  (LoopAgent, max 5 iterations)        │
│       │   ├─► escalation_evaluator  (LlmAgent, EscalationScore)   │
│       │   ├─► EscalationChecker     (BaseAgent — gate)            │
│       │   ├─► agentic_planner       (LlmAgent — no tools)         │
│       │   └─► agentic_executor      (LlmAgent + 4 tools)          │
│       └─► evidence_compiler   (LlmAgent — final report)           │
└─────────────────────────┬──────────────────────────────────────────┘
                          │ FunctionTool calls
┌─────────────────────────▼──────────────────────────────────────────┐
│                  Investigation Tools (app/tools.py)                 │
│   search_orders │ search_trades │ search_market_data │ search_comms │
└─────────────────────────┬──────────────────────────────────────────┘
                          │ pandas CSV reads
┌─────────────────────────▼──────────────────────────────────────────┐
│                    Data Layer (data/*.csv)                          │
│         orders.csv │ trades.csv │ market_data.csv │ comms.csv      │
└────────────────────────────────────────────────────────────────────┘
                          │ writes
┌─────────────────────────▼──────────────────────────────────────────┐
│               Agent Outputs (agent_outputs/attempt_N/)             │
│        attempt_N.yaml │ data.xlsx │ closure_note.txt               │
└────────────────────────────────────────────────────────────────────┘
```

---

## 3. Module Design

### 3.1 Configuration Layer (`app/config.py`)

**Responsibility:** Bootstrap API key selection, model selection, and runtime parameters.

#### Classes

```
FXFROConfiguration (dataclass)
├── critic_model: str           # LLM model for evaluator/compiler agents
├── worker_model: str           # LLM model for investigator/planner/executor agents
├── max_investigation_iterations: int = 5
├── escalation_threshold: float = 0.80
├── orders_data_path: str
├── trades_data_path: str
├── market_data_path: str
├── comms_data_path: str
├── output_base_dir: str = "agent_outputs"
├── lookback_minutes: int = 60
├── cancel_rate_threshold: float = 0.70
├── front_run_seconds: int = 60
├── wash_trade_seconds: int = 300
└── anomaly_threshold: float = 0.65

RateLimitTracker
├── _lock: threading.Lock
├── events: list[dict]
├── push(event: dict) → None
├── get_all() → list[dict]
└── clear() → None
```

#### Key Functions

| Function | Purpose |
|---|---|
| `_probe(key, model, timeout)` | HTTP GET to Gemini API to test if key+model combo is live (returns bool) |
| `pick_working_key_and_model()` | Iterates all key×model combos, returns the first 200-OK combination |
| `_install_key_rotation_patch()` | Monkey-patches `Gemini.generate_content_async` to auto-rotate keys on 429 errors |

#### API Key Pool

- Up to 9 candidates (1 from `.env` + 8 hardcoded fallbacks)
- 4 model variants: `gemini-2.5-flash-lite`, `gemini-2.5-flash`, `gemini-2.0-flash-lite`, `gemini-2.0-flash`
- Maximum combos probed: 9 × 4 = **36 combos** before exhaustion

#### Key Rotation Flow

```
generate_content_async called
        │
        ▼
for each (key, model) combo:
        ├── set GOOGLE_API_KEY env var
        ├── evict api_client from instance __dict__ (forces SDK re-init)
        ├── set llm_request.model
        ├── call original generate_content_async
        │     ├── SUCCESS → yield items, return
        │     └── ResourceExhaustedError → push retry event, continue
        ▼
All combos exhausted → push exhausted event, raise last error
```

---

### 3.2 Data Layer (`app/data_loaders.py`)

**Responsibility:** Load, validate, and type-cast CSV source data. Load the base workflow YAML.

#### Schemas

```
ORDERS_SCHEMA:
  order_id, entity_id, symbol, side, order_type,
  quantity (float), price (float), timestamp (datetime), status,
  counterparty, session

TRADES_SCHEMA:
  trade_id, entity_id, symbol, side,
  quantity (float), price (float), timestamp (datetime),
  counterparty, trade_type, session

MARKET_DATA_SCHEMA:
  symbol, timestamp (datetime),
  bid (float), ask (float), mid (float),
  volume (float), spread_bps (float)

COMMS_SCHEMA:
  comm_id, entity_id, timestamp (datetime),
  channel, content, participants
```

#### `_load_csv(path, schema, datetime_col)` Logic

1. Reads CSV with `dtype=str` (avoids premature type coercion)
2. Adds any missing schema columns as empty strings (schema coercion tolerance)
3. Casts `float` columns via `pd.to_numeric(..., errors="coerce").fillna(0.0)`
4. Parses `timestamp` column via `pd.to_datetime(..., errors="coerce")`
5. Returns DataFrame projected to schema key order

#### `BASE_WORKFLOW`

- Loaded **once at import time** from `fx_fro_surveillance.yaml`
- Treated as a **read-only constant** — never mutated
- Provides thresholds, weights, parameter ranges used by all agents

---

### 3.3 Investigation Tools (`app/tools.py`)

All tools are pure Python functions registered as `FunctionTool` instances with the ADK runtime.

#### `_parse_time_window(time_window: str) → (datetime, datetime)`

Parses three formats:
| Format | Example |
|---|---|
| ISO range | `2024-01-15T09:00:00/2024-01-15T10:30:00` |
| Natural language | `09:00-10:30 on 2024-01-15` |
| Single timestamp | `2024-01-15 09:30:00` (applies ±`lookback_minutes`) |

---

#### `search_orders(entity_id, time_window, cancel_rate_threshold=0.70, anomaly_check=True)`

**Algorithm:**

```
1. Load orders CSV
2. Filter: entity_id match (case-insensitive) AND timestamp ∈ [start, end]
3. Compute:
   cancel_rate = cancelled_orders / max(total_orders, 1)
   anomaly_score = min(1.0, cancel_rate / cancel_rate_threshold)
4. Layering detection:
   For each symbol × side combination:
     If cancelled_orders_on_same_side ≥ 3 AND unique_price_levels ≥ 3:
       → append layering_pattern record
5. Return dict with:
   entity_id, time_window, total_orders, cancelled_orders,
   cancel_rate, cancel_rate_threshold, orders_anomaly_score,
   spoofing_flag (cancel_rate ≥ threshold), layering_patterns (list),
   filtered_orders (list of dicts)
```

---

#### `search_trades(entity_id, time_window, wash_trade_check=True, front_run_check=True)`

**Algorithm:**

```
1. Load trades CSV
2. Expand window: [start−30min, end+30min] for context
3. Filter: entity_id match AND timestamp ∈ expanded window

4. WASH TRADE DETECTION (O(n²) in trades per symbol):
   For each symbol:
     Sort trades by timestamp
     For each pair (t1, t2):
       If delta > wash_trade_seconds: break (sorted, no more within window)
       If same counterparty AND opposite sides: → wash_trade_pair

5. FRONT-RUNNING DETECTION:
   Load orders CSV for entity_id in expanded window
   Filter client_orders (trade_type == "client")
   Filter prop_trades  (trade_type == "prop")
   For each (client_order, prop_trade) pair:
     If same symbol AND same side AND 0 < delta ≤ front_run_seconds:
       → front_running_signal

6. anomaly_score:
   wash_trade_pairs found → max(score, 0.70)
   front_running_signals found → max(score, 0.85)

7. Return: entity_id, time_window, total_trades, wash_trade_pairs (list),
   front_running_signals (list), trades_anomaly_score, filtered_trades (list)
```

---

#### `search_market_data(symbol, time_window, impact_window_minutes=10)`

**Algorithm:**

```
1. Load market_data CSV, filter by symbol
2. Define:
   pre_window  = [start−2h, start)
   impact_window = [start, end+impact_window_minutes]
3. price_change_pct = |mean(impact_mid) − mean(pre_mid)| / mean(pre_mid) × 100
4. volume_zscore = (mean(impact_vol) − mean(pre_vol)) / std(pre_vol)
5. anomaly_score:
   |volume_zscore| > 2.0 → max(score, 0.60)
   price_change_pct > 0.15 → max(score, 0.55)
6. spread_widening_flag = mean(impact_spread) > mean(pre_spread) × 1.5
7. Return: symbol, time_window, price_change_pct, volume_zscore,
   volume_anomaly_flag, spread_widening_flag, market_data_anomaly_score,
   market_data_snapshot (list of dicts from impact window)
```

---

#### `search_comms(entity_id, time_window, keywords=None)`

**Algorithm:**

```
1. Load comms CSV
2. Expand window: [start−30min, end+30min]
3. Filter: entity_id match AND timestamp ∈ expanded window
4. For each comm: keyword scan (case-insensitive substring match)
   → collect matched_keywords per comm
5. coordination_score = min(1.0, total_keyword_hits / max(total_comms, 1) × 0.25)
6. Return: entity_id, time_window, total_comms, keyword_hits (count),
   comms_coordination_score, hit_details (list of matched comm records),
   filtered_comms (all comms in window)
```

Default keyword set: 80+ keywords across 5 SOP categories (pre-trade intent, client intelligence, post-trade confirmation, coordination, evasion language).

---

#### `write_attempt_artifacts(attempt_n, findings, refined_workflow)`

Writes 3 files to `agent_outputs/attempt_{N}/`:

| File | Content |
|---|---|
| `attempt_N.yaml` | Structured YAML: escalation result, refinements vs base YAML, SOP sections invoked, findings summary |
| `data.xlsx` | 5-tab Excel: trades, orders, front_running_book, market_data, comms |
| `closure_note.txt` | Human-readable compliance closure note with full scoring and recommendation |

---

### 3.4 SOP Guidelines (`app/sop_guidelines.py`)

**Read-only** module providing:

| Export | Description |
|---|---|
| `FRO_SOP` | Full 10-section Standard Operating Procedure (string constant injected into LLM prompts) |
| `COMMS_KEYWORDS_FULL` | Dict of 5 keyword categories → lists |
| `COMMS_KEYWORDS_DEFAULT` | Flat list (union of all categories) used as default by `search_comms` |

**SOP Sections:**

| Section | Topic |
|---|---|
| 1 | Alert Intake and Triage (session identification, instrument class) |
| 2 | **Time Window Expansion Rules** (5 rules: A–E) |
| 3 | Order Book Investigation (spoofing, layering, quote stuffing) |
| 4 | Trade Pattern Investigation (front-running, wash trades, internalization abuse) |
| 5 | Market Data Investigation (price impact, volume anomaly, spread analysis) |
| 6 | Communications Investigation (keyword scoring, participant analysis) |
| 7 | Trader History & Counterparty Checks (iteration ≥ 2 only) |
| 8 | Cross-Referencing and Pattern Synthesis (temporal alignment, narrative score) |
| 9 | Escalation Scoring Criteria |
| 10 | Evidence Documentation Requirements |

---

### 3.5 Agent Pipeline (`app/agent.py`)

#### Pydantic Output Models

```python
EscalationScore:
  score: float           # 0.0–1.0
  reasoning: str
  follow_up_queries: list[str] | None

PlanGoal:
  step: int              # 1–5
  tag: str               # ORDERS | TRADES | MARKET | COMMS | SYNTHESIS
  action: str            # Analyze | Identify | Review | Examine | Compute
  description: str

InvestigationPlan:
  entity_id: str
  symbol: str
  time_window: str
  investigation_goals: list[PlanGoal]   # exactly 5
  prose: str                            # markdown numbered list
```

#### Callbacks

| Callback | Trigger | Purpose |
|---|---|---|
| `initialize_workflow_callback` | `before_agent` on root | Deep-copies `BASE_WORKFLOW` → `state["active_workflow"]` once per session |
| `collect_evidence_callback` | `after_agent` on data/agentic agents | Scans all session events, merges tool responses + LLM JSON outputs into `state["surveillance_findings"]`. Also back-propagates `refined_workflow` parameter changes into `state["active_workflow"]` |
| `evidence_folder_callback` | `after_agent` on `evidence_compiler` | Backfills any missing filtered record arrays, calls `write_attempt_artifacts`, returns an `artifact_written` JSON payload as a `genai_types.Content` event |

#### `_smart_merge(existing, data)` Logic

Prevents a list-of-dicts from being overwritten by a less-rich list-of-scalars — if the existing value is a non-empty list-of-dicts and the incoming value is a list-of-non-dicts, the existing value is preserved.

#### Custom Agent: `EscalationChecker(BaseAgent)`

```
_run_async_impl:
  1. Read escalation_score_data.score from session state
  2. Increment state["current_attempt"]
  3. If score ≥ escalation_threshold:
     Yield Event(actions=EventActions(escalate=True))   → exits LoopAgent
  4. Else:
     Yield Event (no escalate flag)                     → loop continues
```

#### Agent Definitions

| Agent | Model | Tools | Output Key | Description |
|---|---|---|---|---|
| `fx_plan_generator` | worker | none | n/a | Structured 5-goal investigation plan (no output_schema — prose parsed by frontend regex) |
| `data_investigator` | worker | all 4 | `surveillance_findings` | Runs all 4 tools in sequence, merges output into single JSON |
| `escalation_evaluator` | critic | none | `escalation_score_data` | Computes weighted escalation score per formula with bonuses |
| `agentic_planner` | worker | none | `agentic_plan` | Decides expanded time windows and refined parameters per SOP rules |
| `agentic_executor` | worker | all 4 | `surveillance_findings` | Executes the plan, calls tools with refined parameters |
| `evidence_compiler` | critic | none | `final_surveillance_report` | Compiles final markdown compliance report |

#### Agent Hierarchy

```
workflow_initializer_agent  (root_agent → app)
│   before_agent_callback: initialize_workflow_callback
│   tools: [AgentTool(fx_plan_generator)]
│   sub_agents: [surveillance_pipeline]
│
└── surveillance_pipeline  (SequentialAgent)
    ├── data_investigator  (LlmAgent)
    ├── investigation_loop (LoopAgent, max_iterations=5)
    │   ├── escalation_evaluator  (LlmAgent)
    │   ├── EscalationChecker     (BaseAgent)
    │   ├── agentic_planner       (LlmAgent)
    │   └── agentic_executor      (LlmAgent)
    └── evidence_compiler  (LlmAgent)
```

---

### 3.6 Backend Server (`server.py`)

Built on `google.adk.cli.fast_api.get_fast_api_app()`.

#### Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/apps/app/users/{user_id}/sessions/{session_id}` | Create ADK session |
| `POST` | `/api/run_sse` | Run agent, stream SSE events |
| `GET`  | `/api/docs` | Swagger UI (used as health check by frontend) |
| `GET`  | `/api/rate-limit-status` | Return queued key-rotation events from `RateLimitTracker` |
| `DELETE` | `/api/rate-limit-status` | Clear rate-limit event queue |
| `GET`  | `/files/{path}` | Serve static files from `agent_outputs/` |

---

### 3.7 Frontend (`frontend/`)

**Stack:** React 18 + TypeScript + Vite + Tailwind CSS + Shadcn UI

#### Key State

| State Variable | Type | Purpose |
|---|---|---|
| `messages` | `MessageWithAgent[]` | Chat conversation (human + AI) |
| `messageEvents` | `Map<messageId, ProcessedEvent[]>` | Per-message investigation timeline events |
| `displayData` | `string \| null` | Current report content |
| `xlsxPath` | `string \| null` | Path for XLSX download button |
| `isLoading` | `boolean` | SSE stream in progress |
| `isBackendReady` | `boolean` | Backend health check status |

#### SSE Event Processing Pipeline

```
/api/run_sse SSE stream
       │
       ▼
Reader → LineBuffer → EventDataBuffer
       │
       ▼
processSseEventData(jsonData, aiMessageId)
       │
       ├── extractDataFromSSE(jsonData)
       │    ├── Parse author, textParts, functionCall, functionResponse
       │    ├── Extract stateDelta fields (final_surveillance_report, etc.)
       │    └── Build surveillanceEvent by agent type:
       │         investigator_result, escalation_score, escalation_check,
       │         sop_invoked, agentic_plan, artifact_written, workflow_*
       │
       ├── Handle functionCall/functionResponse
       │    └── fx_plan_generator response → parsePlanGoals() regex parsing
       │
       ├── Add timeline event via addTimelineEvent()
       │
       └── If evidence_compiler + finalReportWithCitations:
            Add final report AI message + attach XLSX download
```

#### Timeline Event Types and UI Cards

| Event Type | Rendered As |
|---|---|
| `plan_generating` | Spinner card ("generating plan...") |
| `plan_structured` | 5-step plan card with YAML badge |
| `investigator_result` | Anomaly score card with spoofing/wash/FR counts |
| `escalation_score` | Score gauge + reasoning + follow-up queries |
| `escalation_check` | ESCALATE banner or "continuing loop" badge |
| `agentic_plan` | Investigation plan with time window expansion detail |
| `sop_invoked` | SOP cycle card with refinement delta |
| `artifact_written` | Evidence package card with YAML preview + download |
| `workflow_initialized` | Active workflow thresholds card |
| `workflow_updated` | Parameter update diff card |
| `rate_limit_retry` | Key rotation warning banner |
| `rate_limit_exhausted` | Quota exhausted error card |

---

## 4. Agent Interaction Flow

```
User types alert
      │
      ▼
workflow_initializer_agent
├── Calls fx_plan_generator (via AgentTool)
│   └── Returns 5-goal InvestigationPlan
├── Presents plan to user
│
├── [User refines] → loop back, call fx_plan_generator again
│
├── [User approves] → store plan in state["surveillance_plan"]
│   └── Delegates to surveillance_pipeline
│
surveillance_pipeline (Sequential)
├── data_investigator
│   ├── search_orders(entity_id, time_window)
│   ├── search_trades(entity_id, time_window)
│   ├── search_market_data(symbol, time_window)
│   ├── search_comms(entity_id, time_window)
│   └── → state["surveillance_findings"]
│
├── investigation_loop (max 5 iterations)
│   │
│   ├── [Iteration N]
│   │   ├── escalation_evaluator
│   │   │   └── → state["escalation_score_data"] {score, reasoning, follow_up_queries}
│   │   ├── EscalationChecker
│   │   │   ├── score ≥ 0.80 → escalate=True → EXIT LOOP
│   │   │   └── score < 0.80 → continue
│   │   ├── agentic_planner
│   │   │   └── → state["agentic_plan"] {expanded_window, parameters, tools_sequence, SOP rules}
│   │   └── agentic_executor
│   │       ├── search_orders(refined params)
│   │       ├── search_trades(refined params)
│   │       ├── search_market_data(refined params)
│   │       ├── search_comms(refined params)
│   │       └── → state["surveillance_findings"] (merged via collect_evidence_callback)
│   │
│   └── [Repeat or escalate]
│
└── evidence_compiler
    ├── Reads surveillance_findings, escalation_score_data, surveillance_plan
    ├── Produces final markdown report → state["final_surveillance_report"]
    └── evidence_folder_callback:
        ├── write_attempt_artifacts(...)
        └── Returns artifact_written event to frontend
```

---

## 5. Data Schemas

### Orders CSV

| Column | Type | Notes |
|---|---|---|
| `order_id` | str | Unique identifier (e.g., `ORD-001`) |
| `entity_id` | str | Trader/desk ID (e.g., `SMITH_J`, `FX_PROP_1`) |
| `symbol` | str | FX pair (e.g., `EUR/USD`) |
| `side` | str | `BUY` or `SELL` |
| `order_type` | str | `LIMIT` or `MARKET` |
| `quantity` | float | Notional amount |
| `price` | float | Order price |
| `timestamp` | datetime | ISO-8601 or `YYYY-MM-DD HH:MM:SS` |
| `status` | str | `FILLED` or `CANCELLED` |
| `counterparty` | str | Counterparty bank code |
| `session` | str | `LONDON`, `TOKYO`, or `NEW YORK` |

### Trades CSV

| Column | Type | Notes |
|---|---|---|
| `trade_id` | str | Unique identifier |
| `entity_id` | str | Trader/desk ID |
| `symbol` | str | FX pair |
| `side` | str | `BUY` or `SELL` |
| `quantity` | float | Notional amount |
| `price` | float | Execution price |
| `timestamp` | datetime | Execution timestamp |
| `counterparty` | str | Counterparty code |
| `trade_type` | str | **`client`** (agency) or **`prop`** (proprietary) |
| `session` | str | Trading session |

### Market Data CSV

| Column | Type | Notes |
|---|---|---|
| `symbol` | str | FX pair |
| `timestamp` | datetime | Tick timestamp |
| `bid` | float | Best bid |
| `ask` | float | Best ask |
| `mid` | float | Mid price `(bid+ask)/2` |
| `volume` | float | Volume at tick |
| `spread_bps` | float | Spread in basis points |

### Communications CSV

| Column | Type | Notes |
|---|---|---|
| `comm_id` | str | Unique identifier |
| `entity_id` | str | Primary participant (trader/desk) |
| `timestamp` | datetime | Communication timestamp |
| `channel` | str | `CHAT`, `PHONE`, `EMAIL` |
| `content` | str | Full message text |
| `participants` | str | Pipe-delimited participant list |

---

## 6. Escalation Scoring Model

### Base Formula

```
score = (orders_anomaly_score  × 0.25)
      + (trades_anomaly_score  × 0.35)
      + (market_anomaly_score  × 0.20)
      + (comms_coordination    × 0.20)
```

### Bonuses (applied after weighted total, hard cap at 1.0)

| Condition | Bonus |
|---|---|
| `front_running_signals ≥ 1` | +0.15 |
| `wash_trade_pairs ≥ 2` | +0.10 |
| `spoofing_flag = True` | +0.10 |
| `EVASION_LANGUAGE` keyword category hit | +0.05 |
| `narrative_score ≥ 0.80` (Section 8.2) | +0.05 |
| `EXTERNAL_COORDINATION` flag | +0.05 |
| Each plausible alternative hypothesis | −0.05 |

### Decision Thresholds

| Score Range | Decision | Action |
|---|---|---|
| 0.00–0.30 | **CLOSE** | No meaningful evidence |
| 0.31–0.59 | **MONITOR** | Anomalies present, insufficient for escalation |
| 0.60–0.79 | **INVESTIGATE FURTHER** | Loop continues (up to max 5 iterations) |
| 0.80–1.00 | **ESCALATE** | Refer to Compliance immediately |

### Narrative Score (Section 8.2)

Five front-running narrative elements, each scored 0 (absent) or 1 (present):

| Element | Indicator |
|---|---|
| (a) | Pre-trade comms showing knowledge of client order |
| (b) | Prop pre-positioning before client order |
| (c) | Client order execution found |
| (d) | Prop position closed at profit after client fill |
| (e) | Price moved in direction of prop trade |

`narrative_score = sum(elements) / 5`

### Component Score Computation

| Component | Tools | Anomaly Score Logic |
|---|---|---|
| Orders | `search_orders` | `min(1.0, cancel_rate / threshold)` |
| Trades | `search_trades` | Base 0; +0.70 if wash trades; +0.85 if front-running |
| Market | `search_market_data` | +0.60 if `\|vol_zscore\| > 2`; +0.55 if `price_chg > 0.15%` |
| Comms | `search_comms` | `min(1.0, keyword_hits / total_comms × 0.25)` |

---

## 7. Artifact Output Specification

### `attempt_N.yaml` Structure

```yaml
attempt: N
generated_at: <ISO-8601 UTC>
entity_id: <str>
symbol: <str>
escalation_score: <float>
escalation_decision: ESCALATE | INVESTIGATE_FURTHER | MONITOR
base_workflow_ref: fx_fro_surveillance.yaml
investigation_type: rules_based | agentic
sop_sections_invoked: [...]
time_expansion_rules_applied: [...]
comms_categories_hit: [...]
extra_checks_performed: [...]
refinements_from_base:
  time_window:
    base: <str>
    expanded_to: <str>
    expansion_reason: <str>
  cancel_rate_threshold:
    base: 0.70
    used: <float>
  front_run_seconds:
    base: 60
    used: <int>
  wash_trade_seconds:
    base: 300
    used: <int>
  comms_keywords:
    base_count: 13
    used_count: <int>
    keywords_used: [...]
findings_delta: <dict>
findings_summary:
  orders_anomaly_score: <float>
  trades_anomaly_score: <float>
  market_data_anomaly_score: <float>
  comms_coordination_score: <float>
  spoofing_flag: <bool>
  wash_trade_pairs_count: <int>
  front_running_signals_count: <int>
  comms_keyword_hits: <int>
  narrative_score: <float>
  alternative_hypotheses: [...]
```

### `data.xlsx` Tabs

| Tab Name | Source Data |
|---|---|
| `trades` | `filtered_trades` from `search_trades` |
| `orders` | `filtered_orders` from `search_orders` |
| `front_running_book` | `front_running_signals` (or `wash_trade_pairs` if empty) |
| `market_data` | `market_data_snapshot` from `search_market_data` |
| `comms` | `hit_details` from `search_comms` |

### `closure_note.txt` Sections

```
FX-FRO SURVEILLANCE CLOSURE NOTE — Attempt N
============================================================
Timestamp | Entity | Symbol | Investigation Type
Base Window | Expanded Window | Escalation Score | Decision

SOP PROCEDURE FOLLOWED       [x] Section list
TIME WINDOW EXPANSION        Base → Expanded, rules fired
FINDINGS SUMMARY             All 4 component scores + flags
COMMS KEYWORD CATEGORIES HIT [!] category list
ALTERNATIVE HYPOTHESES CONSIDERED
REASONING                    Full LLM reasoning text
FOLLOW-UP QUERIES FOR NEXT CYCLE
[ ESCALATED banner if score ≥ 0.80 ]
```

---

## 8. API Endpoints

### POST `/api/run_sse`

**Request body:**
```json
{
  "appName": "app",
  "userId": "u_999",
  "sessionId": "<uuid>",
  "newMessage": {
    "parts": [{"text": "<user query>"}],
    "role": "user"
  },
  "streaming": false
}
```

**Response:** `text/event-stream` (SSE)

Each event is a line `data: <json>\n\n` where the JSON contains:
- `author`: agent name
- `content.parts`: text parts and/or function call/response parts
- `actions.stateDelta`: state key changes (e.g., `surveillance_findings`, `escalation_score_data`)

---

## 9. State Management

The ADK session `state` dict is the shared memory between all agents in a pipeline run.

| State Key | Set By | Read By |
|---|---|---|
| `active_workflow` | `initialize_workflow_callback`, `collect_evidence_callback` | All agents |
| `surveillance_plan` | `workflow_initializer_agent` | `data_investigator`, `evidence_compiler` |
| `surveillance_findings` | `data_investigator`, `agentic_executor` (via `output_key`) + `collect_evidence_callback` | `escalation_evaluator`, `evidence_compiler` |
| `escalation_score_data` | `escalation_evaluator` | `EscalationChecker`, `agentic_planner`, `agentic_executor` |
| `agentic_plan` | `agentic_planner` | `agentic_executor` |
| `current_attempt` | `EscalationChecker` (increments each iteration) | `agentic_planner`, `agentic_executor` |
| `final_surveillance_report` | `evidence_compiler` | Frontend (via `stateDelta`) |
| `last_artifact_paths` | `evidence_folder_callback` | Frontend (via `stateDelta`) |
| `alert_details` | User message / `workflow_initializer_agent` | `evidence_compiler` |

---

## 10. Key Algorithms

### Time Window Expansion (SOP Section 2)

Rules applied **in order**, taking the widest window any rule triggers:

| Rule | Trigger Condition | Expansion |
|---|---|---|
| **A** | `cancel_rate > 0.50` | `start − 90 min` |
| **B** | `front_running_signals > 0` | `start − 120 min` |
| **C** | `wash_trade_pairs ≥ 2` | Full session window |
| **D** | `comms_keyword_hits ≥ 5` | Comms window: `start − 120 min` |
| **E** | `volume_zscore > 3.0` | Market window: `start − 180 min, end + 60 min` |

### Wash Trade Detection (O(n²) per symbol)

```python
For symbol in symbols:
    sorted_trades = sort(trades_for_symbol, by=timestamp)
    For i, t1 in enumerate(sorted_trades):
        For t2 in sorted_trades[i+1:]:
            delta = (t2.timestamp - t1.timestamp).seconds
            if delta > wash_trade_seconds: break   # sorted → no more pairs
            if t1.counterparty == t2.counterparty AND t1.side != t2.side:
                → wash_trade_pair detected
```

### Front-Running Detection (O(m×n) orders × trades)

```python
client_orders = orders[trade_type == "client"]
prop_trades   = trades[trade_type == "prop"]
For co in client_orders:
    For pt in prop_trades:
        if co.symbol == pt.symbol:
            delta = (pt.timestamp - co.timestamp).seconds
            if 0 < delta ≤ front_run_seconds AND co.side == pt.side:
                → front_running_signal
```

### Coordinated Evidence Merge (`collect_evidence_callback`)

Scans **all session events** (not just latest) and merges into `surveillance_findings`:
1. Priority 1: `function_response` parts (preserves list-of-dicts)
2. Priority 2: LLM text parts that start with `{` (JSON summaries)
3. Uses `_smart_merge` to never downgrade richer data structures

---

## 11. Configuration Reference

### `fx_fro_surveillance.yaml` (Base Workflow — Read-Only)

```yaml
thresholds:
  escalation: 0.80
  spoofing_cancel_rate: 0.70
  layering_min_levels: 3
  front_running_seconds: 60
  wash_trade_seconds: 300
  volume_zscore: 2.0
  price_impact_pct: 0.15
  comms_coordination_score: 0.30

scoring_weights:
  orders_anomaly: 0.25
  trades_anomaly: 0.35
  market_data_anomaly: 0.20
  comms_coordination: 0.20

parameter_ranges:
  front_run_seconds:     {min: 30,   max: 300, base: 60}
  wash_trade_seconds:    {min: 60,   max: 900, base: 300}
  cancel_rate_threshold: {min: 0.50, max: 0.95, base: 0.70}
  lookback_minutes:      {min: 30,   max: 240, base: 60}
  comms_lookback_minutes:{min: 60,   max: 360, base: 90}
```

### `FXFROConfiguration` Defaults

| Parameter | Default | Description |
|---|---|---|
| `max_investigation_iterations` | 5 | Max loop iterations before forced exit |
| `escalation_threshold` | 0.80 | Score above which investigation escalates |
| `lookback_minutes` | 60 | Default single-timestamp window expansion |
| `cancel_rate_threshold` | 0.70 | Spoofing suspected above this cancel rate |
| `front_run_seconds` | 60 | Max seconds between client order and prop trade to flag |
| `wash_trade_seconds` | 300 | Max seconds between round-trip trades with same CP |
| `anomaly_threshold` | 0.65 | General anomaly score floor |

---

## 12. Error Handling & Resilience

### API Rate Limit (429) Handling

- **Detection:** `_ResourceExhaustedError` from `google.adk.models`
- **Response:** Rotate to next (key, model) combo from pool of up to 36 combos
- **Frontend Visibility:** `RateLimitTracker` pushes events; frontend polls `/api/rate-limit-status` every 600ms during active requests and renders retry/exhausted cards in the timeline

### Data Loading Resilience

- Missing CSV files → empty DataFrame with correct schema (no crash)
- Missing columns → filled with empty strings
- Parse errors (`pd.to_numeric`, `pd.to_datetime`) → coerced to `0.0` / `NaT`

### Frontend SSE Resilience

- Session creation: exponential backoff retry (up to 10 attempts, max 5s delay, 2-min timeout)
- Backend health check: polls `GET /api/docs` every 2s for up to 2 minutes
- SSE message send: same retry-with-backoff wrapper

### Artifact Backfill

If the LLM agent omits filtered record arrays in its output, `evidence_folder_callback` directly calls the tool functions (`search_orders`, `search_trades`, etc.) to backfill them before writing artifacts — ensuring XLSX tabs are never empty due to LLM truncation.

### XLSX Comms Normalization

If the LLM serializes `hit_details` as a list-of-lists (degraded from list-of-dicts), the artifact writer detects this and reconstructs the dict structure using alphabetical key ordering before writing the Excel tab.

---

*End of Low-Level Design Document*
