"""
Standard Operating Procedures for FX Front-Running-Order (FX-FRO) Surveillance.

This module contains the full procedural SOP used by the agentic_investigator.
It is read-only — agents follow it, they never modify it.
"""

FRO_SOP = """
=============================================================================
STANDARD OPERATING PROCEDURE: FX FRONT-RUNNING ORDER (FX-FRO) INVESTIGATION
Version 1.0 | Compliance Surveillance Division
=============================================================================

This SOP governs every agentic investigation cycle. Follow each section in
order. Document which sections you invoked and why in your output JSON under
the key "sop_sections_invoked".

─────────────────────────────────────────────────────────────────────────────
SECTION 1: ALERT INTAKE AND TRIAGE
─────────────────────────────────────────────────────────────────────────────
1.1  Parse from the alert: entity_id, symbol, base_time_window.
1.2  Identify trading session from the time window:
       - TOKYO  : 00:00–08:00 UTC
       - LONDON : 07:00–16:00 UTC  (overlap zone 07:00–08:00)
       - NEW YORK: 12:00–21:00 UTC (overlap zone 12:00–16:00)
     Session matters because wash trade and cancel patterns differ by session.
1.3  Identify the instrument class:
       - Major pair  (EUR/USD, GBP/USD, USD/JPY): tightest spreads, highest
         liquidity — spoofing and layering are more common.
       - Cross pair  (EUR/GBP, EUR/JPY): wider spreads — wash trades more
         visible relative to volume.
       - EM pair     (USD/TRY, USD/BRL): front-running riskier, look for
         larger delta in front_run_seconds (up to 120s).
1.4  Set investigation_type = "agentic" and record base_time_window.

─────────────────────────────────────────────────────────────────────────────
SECTION 2: TIME WINDOW EXPANSION RULES
─────────────────────────────────────────────────────────────────────────────
Start from the base time window given in the alert. Then apply these rules
IN ORDER — take the widest window that any rule triggers:

Rule A — Cancel rate > 0.50 in initial scan:
  Expand to: base_start − 90 min, base_end + 30 min
  Reason: Pre-positioning for spoofing typically begins 60–90 min before the
          suspicious trade.

Rule B — Front-running signals found (any count):
  Expand to: base_start − 120 min, base_end + 30 min
  Reason: Proprietary pre-positioning for front-running often starts 1–2 hours
          before the client order arrives.

Rule C — Wash trade pairs found (≥ 2 pairs):
  Expand to: full session (session_start, session_end)
  Reason: Wash trading is usually systematic within a single session.

Rule D — Comms keyword hits ≥ 5:
  Expand comms window by an additional − 120 min before the base_start.
  Reason: Pre-trade coordination typically happens well before execution.

Rule E — Market volume Z-score > 3.0:
  Expand market data window to: base_start − 180 min, base_end + 60 min
  Reason: Volume anomalies of this magnitude indicate a prolonged buildup.

Document which rules fired under "time_expansion_rules_applied" in your output.

─────────────────────────────────────────────────────────────────────────────
SECTION 3: ORDER BOOK INVESTIGATION PROCEDURE
─────────────────────────────────────────────────────────────────────────────
Call search_orders with the EXPANDED time window (from Section 2).

3.1  SPOOFING CHECK
     - Cancel rate threshold (from base YAML): 0.70
     - If cancel_rate > 0.70: flag as SPOOFING_SUSPECTED
     - If cancel_rate > 0.50 but ≤ 0.70: flag as BORDERLINE — lower threshold
       to 0.60 on the next call and note in refined YAML.
     - Spoofing signal strengthens if: orders were large (>5M notional) AND
       placed in rapid succession (<30 seconds apart) AND all cancelled within
       60 seconds of each other.

3.2  LAYERING CHECK
     - Look for ≥ 3 orders on the same side at different price levels, all
       cancelled after market moves in the intended direction.
     - Layering is confirmed when: the stacked orders span >10 bps price range
       AND all are cancelled within 5 minutes of each other.
     - Note: layering on the BID side to push price up before a PROP BUY is
       the most common FX FRO variant.

3.3  QUOTE STUFFING CHECK (advanced)
     - If total_orders in the window > 20 for a single entity: check for
       bursts of >5 orders within any 10-second window.
     - Quote stuffing is used to slow down competing HFT systems.

3.4  PRIOR DAY BASELINE
     - If this is iteration ≥ 2, call search_orders for the same entity_id
       on the prior trading day (same session, same symbol) to establish a
       baseline cancel rate.
     - If today's cancel_rate > 2× baseline: strong spoofing signal.
     - Document baseline_cancel_rate in output.

─────────────────────────────────────────────────────────────────────────────
SECTION 4: TRADE PATTERN INVESTIGATION PROCEDURE
─────────────────────────────────────────────────────────────────────────────
Call search_trades with the EXPANDED time window.

4.1  FRONT-RUNNING CHECK
     - Threshold (from base YAML): client order → prop trade within 60 seconds,
       same symbol, same direction.
     - On iteration ≥ 2: also check 60–120 second range (weaker signal, note
       separately as SOFT_FRONT_RUN).
     - For EM pairs: use 120 seconds as the threshold (lower liquidity).
     - Confirmed front-run requires: (a) client order timestamp < prop trade
       timestamp, (b) same side (both BUY or both SELL), (c) prop trade
       closed (SELL) within 10 minutes of the client fill at a higher price.

4.2  WASH TRADE CHECK
     - Threshold (from base YAML): same counterparty, opposite sides, within
       300 seconds.
     - On iteration ≥ 2: also check 300–600 second range (note as SOFT_WASH).
     - Wash trades generate artificial volume — check if the entity's volume
       for this session is >3× their 30-day average volume. If yes, flag as
       VOLUME_INFLATION.
     - Circular trading pattern: A→B buy then B→A buy (same symbol, same price)
       is the strongest wash signal. Note counterparty_name in evidence.

4.3  INTERNALIZATION ABUSE CHECK
     - Prop desk buys at X, immediately sells to client at X or X+1 pip:
       entity pockets the spread without taking market risk.
     - Check: prop BUY trade followed within 30 seconds by client SELL trade
       at the same or worse price for the client.

4.4  PROP TRADE SEQUENCE CHECK
     - On iteration ≥ 2, map out the full sequence of the entity's prop trades
       in the session: direction changes, timing, sizes.
     - A pattern of: BUY → BUY → BUY → SELL (large) typically indicates
       accumulation before a client-driven price move.

─────────────────────────────────────────────────────────────────────────────
SECTION 5: MARKET DATA INVESTIGATION PROCEDURE
─────────────────────────────────────────────────────────────────────────────
Call search_market_data with the EXPANDED time window.

5.1  PRICE IMPACT CHECK
     - Baseline window: 2 hours before the suspicious trade.
     - Impact window: the suspicious trade time ± 10 minutes.
     - Flag if price moved > 0.15% (15 bps) within the impact window.
     - On iteration ≥ 2: also check if the price STARTED moving before the
       client order was placed (pre-positioning signal).

5.2  VOLUME ANOMALY CHECK
     - Z-score threshold (from base YAML): 2.0
     - Z-score > 3.0: extreme anomaly — note as VOLUME_SPIKE_EXTREME.
     - Z-score > 5.0: almost certainly an algorithmic or institutional event —
       cross-reference with comms for coordination language.

5.3  SPREAD ANALYSIS
     - Spread widening > 1.5× baseline in the impact window: indicates
       liquidity was consumed (consistent with large directional flow).
     - Spread widening before the client order suggests pre-positioning was
       already moving the market.

5.4  PRIOR SESSION COMPARISON (iteration ≥ 2)
     - Compare the volume profile of this session vs. the prior 5 sessions
       for the same symbol.
     - If today's peak volume is >2× the prior 5-session average peak:
       flag as SESSION_VOLUME_ANOMALY.

─────────────────────────────────────────────────────────────────────────────
SECTION 6: COMMUNICATIONS INVESTIGATION PROCEDURE
─────────────────────────────────────────────────────────────────────────────
Call search_comms with the EXPANDED time window.

ALWAYS search with the FULL keyword set below, not just the defaults.
Document which keyword categories matched under "comms_categories_hit".

6.1  PRE-TRADE INTENT KEYWORDS
     These appear BEFORE the trade and indicate the trader knew about
     an upcoming order or was planning to position ahead of it.
       position, loading, size up, going in, risk on, bid, offer,
       buying, selling, accumulating, building, front, ahead of,
       before they, in front, client coming, order coming, watch this,
       about to, going to buy, going to sell, heads up, fyi

6.2  CLIENT INTELLIGENCE KEYWORDS
     These suggest the trader had knowledge of a client's order before
     it was formally received, which is a regulatory breach.
       client, customer, order, flow, they want, they need, amount,
       they're buying, they're selling, client side, customer order,
       agency, their position, on behalf, done deal, confirmed,
       they told me, heard from, tip, intel, information, know about

6.3  POST-TRADE CONFIRMATION KEYWORDS
     These appear AFTER the trade and confirm the strategy worked.
       done, filled, out, flat, gone, covered, off, closed, unwound,
       took profit, p&l, made money, nice, good trade, worked,
       as expected, moved as planned, clean, got it, covered the risk,
       locked in, booked, confirmed, all done, squared

6.4  COORDINATION KEYWORDS
     These suggest two or more traders coordinated their activity.
       you go first, after you, let me know when, same, match,
       together, both, coordinate, align, in sync, agreed, same book,
       you and me, copy that, roger, on your signal, wait for me,
       when you're ready, at the same time, simultaneously, split

6.5  EVASION LANGUAGE KEYWORDS
     Extremely high signal — traders aware of surveillance.
       careful, be careful, watch what you say, delete this,
       off the record, no paper, don't write, call me, use the phone,
       clean, clear, nothing in writing, not on chat, speak later,
       private, personal email, WhatsApp, bloomberg off, voice only

6.6  KEYWORD HIT SCORING
     - Pre-trade intent hit:         +0.20 to coordination_score
     - Client intelligence hit:      +0.25 to coordination_score
     - Post-trade confirmation hit:  +0.10 to coordination_score
     - Coordination keyword hit:     +0.20 to coordination_score
     - Evasion language hit:         +0.30 to coordination_score (cap at 1.0)

6.7  PARTICIPANT ANALYSIS
     - If comms involve more than 2 participants: flag as MULTI_PARTY_COORDINATION.
     - If comms involve a desk head or manager: flag as SUPERVISORY_INVOLVEMENT.
     - If participants include a counterparty trader (not internal): flag as
       EXTERNAL_COORDINATION — highest severity.

─────────────────────────────────────────────────────────────────────────────
SECTION 7: TRADER HISTORY AND COUNTERPARTY CHECKS
─────────────────────────────────────────────────────────────────────────────
On iteration ≥ 2, perform these additional checks:

7.1  TRADER CANCEL RATE BASELINE
     - Call search_orders for entity_id on the PRIOR TRADING DAY
       (shift time_window back by 24 hours, same session).
     - Compute baseline_cancel_rate from prior day.
     - If today's rate > 2× baseline: CANCEL_RATE_ELEVATED_VS_BASELINE.

7.2  COUNTERPARTY FREQUENCY ANALYSIS
     - From filtered_trades: count how many trades involve the SAME counterparty.
     - If any single counterparty appears in > 60% of trades: flag as
       COUNTERPARTY_CONCENTRATION — typical of wash trading arrangements.
     - Note the counterparty name in the evidence.

7.3  WASH TRADE COUNTERPARTY CHECK
     - For each wash trade pair found: check if the same counterparty appears
       in the comms hits.
     - A comms hit referencing the counterparty bank + coordination language
       is near-conclusive evidence of arranged wash trades.

7.4  PRIOR ALERTS CHECK
     - If surveillance_findings already contains a "prior_alert_count" key
       from a previous investigation on this entity: note it.
     - Repeat offenders should have their escalation score boosted by +0.05.

7.5  DESK-LEVEL PATTERN
     - If entity_id looks like a desk code (e.g. FX_PROP_1, G10_DESK):
       note that the pattern may be desk-wide, not individual.
     - Recommend expanding the investigation to other traders on the same desk
       in your follow_up_queries.

─────────────────────────────────────────────────────────────────────────────
SECTION 8: CROSS-REFERENCING AND PATTERN SYNTHESIS
─────────────────────────────────────────────────────────────────────────────
After running tools, synthesise findings across all four data types.

8.1  TEMPORAL ALIGNMENT CHECK
     Align timestamps across orders, trades, comms, and market data:
     - Did comms showing "position" precede the prop trade? (strongest signal)
     - Did the prop trade precede the client fill? (front-running)
     - Did cancel activity precede the price move? (layering/spoofing)
     - Did volume spike align with the prop trade, not the client trade?
       (suggests prop trade CAUSED the volume, not the client order)

8.2  THE FRONT-RUNNING NARRATIVE
     The complete front-running narrative requires ALL of:
     (a) Pre-trade comms showing knowledge of client order [COMMS]
     (b) Prop pre-positioning orders or trades before client [ORDERS/TRADES]
     (c) Client order execution [TRADES]
     (d) Prop position closed at profit after client fills [TRADES]
     (e) Price moved in the direction of the prop trade [MARKET]
     Score each element: 0 = absent, 1 = present. Sum / 5 = narrative_score.
     Include narrative_score in your output JSON.

8.3  ALTERNATIVE HYPOTHESES
     Before escalating, consider and document why each of these might explain
     the data WITHOUT wrongdoing:
     - The prop trade was coincidental (same market view, not client-informed)
     - Cancel activity was due to a system error or algorithmic strategy
     - Volume spike was due to a macro news event at that time
     - Comms keywords were used in a different context (e.g., "position" in
       a risk management sense)
     If any alternative is plausible, reduce the score by 0.05 and document it.

─────────────────────────────────────────────────────────────────────────────
SECTION 9: ESCALATION SCORING CRITERIA
─────────────────────────────────────────────────────────────────────────────
Final weighted score formula (weights from base YAML):
  score = (orders_anomaly_score × 0.25)
        + (trades_anomaly_score × 0.35)
        + (market_data_anomaly_score × 0.20)
        + (comms_coordination_score × 0.20)

Bonuses (applied after weighted score, hard cap at 1.0):
  + 0.15  if front_running_signals ≥ 1
  + 0.10  if wash_trade_pairs ≥ 2
  + 0.10  if spoofing_flag = True
  + 0.05  if EXTERNAL_COORDINATION flag set
  + 0.05  if EVASION_LANGUAGE found in comms
  + 0.05  if narrative_score (Section 8.2) ≥ 0.80
  − 0.05  per plausible alternative hypothesis (Section 8.3)

Escalation decisions:
  0.00 – 0.30 : CLOSE    (no meaningful evidence)
  0.31 – 0.59 : MONITOR  (anomalies present, insufficient for escalation)
  0.60 – 0.79 : INVESTIGATE FURTHER (loop continues)
  0.80 – 1.00 : ESCALATE (refer to Compliance)

─────────────────────────────────────────────────────────────────────────────
SECTION 10: EVIDENCE DOCUMENTATION REQUIREMENTS
─────────────────────────────────────────────────────────────────────────────
Your output JSON MUST include the following keys. Missing keys will cause
the investigation to be flagged as incomplete.

Required top-level keys:
  entity_id, symbol, time_window, investigation_type
  sop_sections_invoked          (list of section numbers you followed)
  time_expansion_rules_applied  (list of rules from Section 2 that fired)
  comms_categories_hit          (list from Section 6 categories that matched)
  orders_anomaly_score          (0.0 – 1.0)
  trades_anomaly_score          (0.0 – 1.0)
  market_data_anomaly_score     (0.0 – 1.0)
  comms_coordination_score      (0.0 – 1.0)
  spoofing_flag                 (true/false)
  wash_trade_pairs              (list)
  front_running_signals         (list)
  comms_keyword_hits            (integer)
  narrative_score               (0.0 – 1.0, from Section 8.2)
  alternative_hypotheses_considered (list of strings)
  filtered_orders, filtered_trades, market_data_snapshot, hit_details

Optional keys (include when Section 7 is invoked):
  baseline_cancel_rate
  counterparty_concentration_flag
  prior_alert_count
  multi_party_coordination_flag
  supervisory_involvement_flag
  external_coordination_flag

Refined workflow keys (always include):
  refined_workflow:
    attempt: N
    investigation_type: agentic
    base_workflow_ref: fx_fro_surveillance.yaml
    sop_sections_invoked: [...]
    time_window_base: <original>
    time_window_expanded: <expanded>
    expansion_rules_fired: [...]
    cancel_rate_threshold_used: <float>
    front_run_seconds_used: <int>
    wash_trade_seconds_used: <int>
    comms_keywords_used: [...]
    extra_checks_performed: [...]

=============================================================================
END OF SOP
=============================================================================
"""

# Comms keyword sets for direct use by tools
COMMS_KEYWORDS_FULL = {
    "pre_trade_intent": [
        "position", "loading", "size up", "going in", "risk on",
        "bid", "offer", "buying", "selling", "accumulating", "building",
        "front", "ahead of", "before they", "in front", "client coming",
        "order coming", "watch this", "about to", "going to buy",
        "going to sell", "heads up", "fyi",
    ],
    "client_intelligence": [
        "client", "customer", "order", "flow", "they want", "they need",
        "amount", "they're buying", "they're selling", "client side",
        "agency", "their position", "on behalf", "confirmed",
        "they told me", "heard from", "tip", "intel", "know about",
    ],
    "post_trade_confirmation": [
        "done", "filled", "out", "flat", "gone", "covered", "off",
        "closed", "unwound", "took profit", "nice", "worked",
        "moved as planned", "got it", "covered the risk",
        "locked in", "booked", "all done", "squared",
    ],
    "coordination": [
        "you go first", "after you", "let me know when", "same", "match",
        "together", "both", "coordinate", "align", "in sync", "agreed",
        "same book", "you and me", "on your signal", "when you're ready",
        "at the same time", "simultaneously", "split",
    ],
    "evasion": [
        "careful", "be careful", "watch what you say", "delete this",
        "off the record", "no paper", "don't write", "call me",
        "nothing in writing", "not on chat", "speak later",
        "private", "personal email", "whatsapp", "voice only", "clean",
    ],
}

# Default flat list for search_comms tool (union of all categories)
COMMS_KEYWORDS_DEFAULT: list[str] = [
    kw for kws in COMMS_KEYWORDS_FULL.values() for kw in kws
]
