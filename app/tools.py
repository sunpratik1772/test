"""FX-FRO surveillance tools: CSV-backed FunctionTools for each data type plus artifact writer."""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .config import config
from .data_loaders import load_comms, load_market_data, load_orders, load_trades

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_time_window(time_window: str) -> tuple[datetime, datetime]:
    """Parse a time_window string like '09:00-10:30 on 2024-01-15' or ISO range."""
    time_window = time_window.strip()
    # ISO range: "2024-01-15T09:00:00/2024-01-15T10:30:00"
    if "/" in time_window:
        parts = time_window.split("/")
        return pd.to_datetime(parts[0]), pd.to_datetime(parts[1])
    # "HH:MM-HH:MM on YYYY-MM-DD"
    if " on " in time_window:
        range_part, date_part = time_window.split(" on ")
        start_str, end_str = range_part.strip().split("-")
        date_str = date_part.strip()
        start = pd.to_datetime(f"{date_str} {start_str.strip()}")
        end = pd.to_datetime(f"{date_str} {end_str.strip()}")
        return start, end
    # Single datetime — apply ±lookback_minutes
    ts = pd.to_datetime(time_window)
    delta = timedelta(minutes=config.lookback_minutes)
    return ts - delta, ts + delta


def _score_from_rate(rate: float, threshold: float) -> float:
    """Convert a rate vs threshold into a 0-1 anomaly contribution score."""
    if rate <= 0:
        return 0.0
    return min(1.0, rate / max(threshold, 1e-9))


# ---------------------------------------------------------------------------
# search_orders
# ---------------------------------------------------------------------------

def search_orders(
    entity_id: str,
    time_window: str,
    cancel_rate_threshold: float = 0.70,
    anomaly_check: bool = True,
) -> dict[str, Any]:
    """Search orders for an entity within a time window and compute anomaly signals.

    Args:
        entity_id: Trader or desk identifier to filter orders.
        time_window: Time range string (e.g. '09:00-10:30 on 2024-01-15').
        cancel_rate_threshold: Cancel rate above which spoofing is suspected.
        anomaly_check: If True, compute layering/spoofing anomaly score.

    Returns:
        Dict with keys: entity_id, total_orders, cancelled_orders, cancel_rate,
        cancel_rate_threshold, anomaly_score, spoofing_flag, layering_patterns, filtered_orders.
    """
    df = load_orders(config.orders_data_path)
    start, end = _parse_time_window(time_window)

    mask = (
        (df["entity_id"].str.upper() == entity_id.upper())
        & (df["timestamp"] >= start)
        & (df["timestamp"] <= end)
    )
    filtered = df[mask].copy()

    total = len(filtered)
    cancelled = len(filtered[filtered["status"].str.lower() == "cancelled"])
    cancel_rate = cancelled / max(total, 1)

    anomaly_score = 0.0
    layering_patterns: list[dict] = []

    if anomaly_check and total > 0:
        # Spoofing signal from cancel rate
        anomaly_score = _score_from_rate(cancel_rate, cancel_rate_threshold)

        # Layering: multiple orders on same side at different prices, all cancelled
        for symbol in filtered["symbol"].unique():
            sym_df = filtered[filtered["symbol"] == symbol]
            for side in ["BUY", "SELL"]:
                side_df = sym_df[sym_df["side"].str.upper() == side]
                cancelled_side = side_df[side_df["status"].str.lower() == "cancelled"]
                if len(cancelled_side) >= 3 and len(cancelled_side["price"].unique()) >= 3:
                    layering_patterns.append({
                        "symbol": symbol,
                        "side": side,
                        "cancelled_orders": len(cancelled_side),
                        "price_levels": sorted(cancelled_side["price"].unique().tolist()),
                    })

    filtered_records = []
    for _, row in filtered.iterrows():
        rec = {k: str(v) if pd.notna(v) else "" for k, v in row.items()}
        filtered_records.append(rec)

    return {
        "entity_id": entity_id,
        "time_window": time_window,
        "total_orders": total,
        "cancelled_orders": cancelled,
        "cancel_rate": round(cancel_rate, 4),
        "cancel_rate_threshold": cancel_rate_threshold,
        "orders_anomaly_score": round(anomaly_score, 4),
        "spoofing_flag": cancel_rate >= cancel_rate_threshold,
        "layering_patterns": layering_patterns,
        "filtered_orders": filtered_records,
    }


# ---------------------------------------------------------------------------
# search_trades
# ---------------------------------------------------------------------------

def search_trades(
    entity_id: str,
    time_window: str,
    wash_trade_check: bool = True,
    front_run_check: bool = True,
) -> dict[str, Any]:
    """Search trades for an entity, detect wash trades and front-running signals.

    Args:
        entity_id: Trader or desk identifier.
        time_window: Time range string.
        wash_trade_check: If True, identify wash trade pairs.
        front_run_check: If True, check for client-order-then-prop-trade patterns.

    Returns:
        Dict with keys: entity_id, total_trades, wash_trade_pairs,
        front_running_signals, anomaly_score, filtered_trades.
    """
    df = load_trades(config.trades_data_path)
    start, end = _parse_time_window(time_window)

    # Expand window by 30 min for context
    expanded_start = start - timedelta(minutes=30)
    expanded_end = end + timedelta(minutes=30)

    mask = (
        (df["entity_id"].str.upper() == entity_id.upper())
        & (df["timestamp"] >= expanded_start)
        & (df["timestamp"] <= expanded_end)
    )
    filtered = df[mask].copy()

    wash_trade_pairs: list[dict] = []
    front_running_signals: list[dict] = []
    anomaly_score = 0.0

    if wash_trade_check and len(filtered) >= 2:
        threshold_s = config.wash_trade_seconds
        
        # Sort for merge_asof
        filtered_sorted = filtered.sort_values("timestamp")
        
        # Self-join on counterparty + symbol to find potential wash trades within the time window
        # merge_asof finds the closest previous match (or we can use a standard merge if we want all matches, 
        # but since we want any wash pair, a time-windowed merge is efficient)
        # Using a standard merge with time filtering is safer to catch all pairs within the window:
        merged = pd.merge(
            filtered_sorted, 
            filtered_sorted, 
            on=["symbol", "counterparty"], 
            suffixes=("_1", "_2")
        )
        
        # Filter: trade 2 must be strictly AFTER trade 1, within threshold, and opposite side
        dt = (merged["timestamp_2"] - merged["timestamp_1"]).dt.total_seconds()
        wash_mask = (
            (dt > 0) & 
            (dt <= threshold_s) & 
            (merged["side_1"].str.upper() != merged["side_2"].str.upper()) &
            (merged["trade_id_1"] != merged["trade_id_2"])
        )
        
        wash_df = merged[wash_mask]
        
        for _, row in wash_df.iterrows():
            wash_trade_pairs.append({
                "trade_1": row["trade_id_1"],
                "trade_2": row["trade_id_2"],
                "symbol": row["symbol"],
                "counterparty": row["counterparty"],
                "delta_seconds": round((row["timestamp_2"] - row["timestamp_1"]).total_seconds(), 1),
            })
    if front_run_check:
        # Look for client orders followed by prop trades within front_run_seconds
        orders_df = load_orders(config.orders_data_path)
        
        # Check if trade_type exists in orders_df, otherwise fallback
        has_trade_type = "trade_type" in orders_df.columns
        
        client_orders = orders_df[
            (orders_df["entity_id"].str.upper() == entity_id.upper())
            & (orders_df["timestamp"] >= expanded_start)
            & (orders_df["timestamp"] <= expanded_end)
        ].copy()
        
        if len(client_orders) > 0 and has_trade_type:
             client_orders = client_orders[client_orders["trade_type"].str.lower() == "client"]
            
        prop_trades = filtered[filtered["trade_type"].str.lower() == "prop"] if "trade_type" in filtered.columns else filtered.copy()

        if len(client_orders) > 0 and len(prop_trades) > 0:
            threshold_s = config.front_run_seconds
            
            # Vectorized merge on symbol and side
            # Both need to be upper case for side match
            client_orders["side_upper"] = client_orders["side"].str.upper()
            prop_trades_copy = prop_trades.copy()
            prop_trades_copy["side_upper"] = prop_trades_copy["side"].str.upper()
            
            # Inner join on symbol and side 
            merged_fr = pd.merge(
                client_orders, 
                prop_trades_copy, 
                on=["symbol", "side_upper"], 
                suffixes=("_co", "_pt")
            )
            
            # Filter: prop trade must be AFTER client order but within front_run_seconds
            dt_fr = (merged_fr["timestamp_pt"] - merged_fr["timestamp_co"]).dt.total_seconds()
            fr_mask = (dt_fr > 0) & (dt_fr <= threshold_s)
            
            fr_df = merged_fr[fr_mask]
            
            for _, row in fr_df.iterrows():
                front_running_signals.append({
                    "client_order_id": row["order_id"],
                    "prop_trade_id": row["trade_id"],
                    "symbol": row["symbol"],
                    "side": row["side_co"],
                    "delta_seconds": round((row["timestamp_pt"] - row["timestamp_co"]).total_seconds(), 1),
                    "client_order_time": str(row["timestamp_co"]),
                    "prop_trade_time": str(row["timestamp_pt"]),
                })


    if wash_trade_pairs:
        anomaly_score = max(anomaly_score, 0.70)
    if front_running_signals:
        anomaly_score = max(anomaly_score, 0.85)

    filtered_records = []
    for _, row in filtered.iterrows():
        rec = {k: str(v) if pd.notna(v) else "" for k, v in row.items()}
        filtered_records.append(rec)

    return {
        "entity_id": entity_id,
        "time_window": time_window,
        "total_trades": len(filtered),
        "wash_trade_pairs": wash_trade_pairs,
        "front_running_signals": front_running_signals,
        "trades_anomaly_score": round(anomaly_score, 4),
        "filtered_trades": filtered_records,
    }


# ---------------------------------------------------------------------------
# search_market_data
# ---------------------------------------------------------------------------

def search_market_data(
    symbol: str,
    time_window: str,
    impact_window_minutes: int = 10,
) -> dict[str, Any]:
    """Search market data for price impact and volume anomalies around a time window.

    Args:
        symbol: FX symbol e.g. 'EUR/USD'.
        time_window: Time range string.
        impact_window_minutes: Window around suspicious time to compute impact.

    Returns:
        Dict with keys: symbol, price_change_pct, volume_zscore,
        volume_anomaly_flag, spread_widening_flag, anomaly_score, market_data_snapshot.
    """
    df = load_market_data(config.market_data_path)
    start, end = _parse_time_window(time_window)

    sym_mask = df["symbol"].str.upper() == symbol.upper()
    sym_df = df[sym_mask].sort_values("timestamp")

    # Pre-window data for baseline
    pre_start = start - timedelta(hours=2)
    pre_df = sym_df[(sym_df["timestamp"] >= pre_start) & (sym_df["timestamp"] < start)]

    # Impact window
    impact_end = end + timedelta(minutes=impact_window_minutes)
    impact_df = sym_df[(sym_df["timestamp"] >= start) & (sym_df["timestamp"] <= impact_end)]

    anomaly_score = 0.0
    price_change_pct = 0.0
    volume_zscore = 0.0

    if len(pre_df) > 0 and len(impact_df) > 0:
        pre_mid = float(pre_df["mid"].mean())
        post_mid = float(impact_df["mid"].mean())
        if pre_mid > 0:
            price_change_pct = float(abs((post_mid - pre_mid) / pre_mid * 100))

        pre_vol_mean = float(pre_df["volume"].mean())
        pre_vol_std = float(pre_df["volume"].std() or 1.0)
        impact_vol = float(impact_df["volume"].mean())
        volume_zscore = float((impact_vol - pre_vol_mean) / pre_vol_std)

        if abs(volume_zscore) > 2.0:
            anomaly_score = max(anomaly_score, 0.60)
        if price_change_pct > 0.15:
            anomaly_score = max(anomaly_score, 0.55)

    spread_widening_flag = False
    if len(pre_df) > 0 and len(impact_df) > 0:
        pre_spread = float(pre_df["spread_bps"].mean())
        impact_spread = float(impact_df["spread_bps"].mean())
        spread_widening_flag = bool(impact_spread > pre_spread * 1.5)

    snapshot = []
    for _, row in impact_df.iterrows():
        snapshot.append({k: str(v) if pd.notna(v) else "" for k, v in row.items()})

    return {
        "symbol": symbol,
        "time_window": time_window,
        "price_change_pct": round(price_change_pct, 4),
        "volume_zscore": round(volume_zscore, 4),
        "volume_anomaly_flag": bool(abs(volume_zscore) > 2.0),
        "spread_widening_flag": spread_widening_flag,
        "market_data_anomaly_score": round(anomaly_score, 4),
        "market_data_snapshot": snapshot,
    }


# ---------------------------------------------------------------------------
# search_comms
# ---------------------------------------------------------------------------

def search_comms(
    entity_id: str,
    time_window: str,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Search communications for an entity, matching surveillance keywords.

    Args:
        entity_id: Trader identifier.
        time_window: Time range string.
        keywords: Keywords to search for (defaults to FRO SOP keyword set).

    Returns:
        Dict with keys: entity_id, total_comms, keyword_hits,
        coordination_score, hit_details, filtered_comms.
    """
    if keywords is None:
        # Default to the full SOP keyword set (all 5 categories)
        from .sop_guidelines import COMMS_KEYWORDS_DEFAULT
        keywords = COMMS_KEYWORDS_DEFAULT

    df = load_comms(config.comms_data_path)
    start, end = _parse_time_window(time_window)

    # Expand window ±30 min
    exp_start = start - timedelta(minutes=30)
    exp_end = end + timedelta(minutes=30)

    mask = (
        (df["entity_id"].str.upper() == entity_id.upper())
        & (df["timestamp"] >= exp_start)
        & (df["timestamp"] <= exp_end)
    )
    filtered = df[mask].copy()

    keyword_hits: list[dict] = []
    for _, row in filtered.iterrows():
        content_lower = str(row["content"]).lower()
        matched = [kw for kw in keywords if kw.lower() in content_lower]
        if matched:
            keyword_hits.append({
                "comm_id": row["comm_id"],
                "timestamp": str(row["timestamp"]),
                "channel": row["channel"],
                "matched_keywords": matched,
                "content": row["content"],
                "participants": row["participants"],
            })

    # Coordination score: fraction of comms with keyword hits, weighted by hit count
    total = len(filtered)
    if total == 0:
        coordination_score = 0.0
    else:
        hit_weight = sum(len(h["matched_keywords"]) for h in keyword_hits)
        coordination_score = min(1.0, (hit_weight / max(total, 1)) * 0.25)

    filtered_records = []
    for _, row in filtered.iterrows():
        filtered_records.append({k: str(v) if pd.notna(v) else "" for k, v in row.items()})

    return {
        "entity_id": entity_id,
        "time_window": time_window,
        "total_comms": total,
        "keyword_hits": len(keyword_hits),
        "comms_coordination_score": round(coordination_score, 4),
        "hit_details": keyword_hits,
        "filtered_comms": filtered_records,
    }


# ---------------------------------------------------------------------------
# Aggregated Async Tool (for concurrent execution)
# ---------------------------------------------------------------------------

async def search_all_data(
    entity_id: str,
    symbol: str, 
    time_window: str,
    cancel_rate_threshold: float = 0.70,
    front_run_seconds: int = 60,
    wash_trade_seconds: int = 300,
    impact_window_minutes: int = 10,
) -> dict[str, Any]:
    """Concurrently search orders, trades, market data, and comms for a given entity and time window."""
    
    # Run the synchronous pandas operations in threads
    orders_task = asyncio.to_thread(search_orders, entity_id, time_window, cancel_rate_threshold, True)
    trades_task = asyncio.to_thread(search_trades, entity_id, time_window, True, True)
    market_task = asyncio.to_thread(search_market_data, symbol, time_window, impact_window_minutes)
    comms_task  = asyncio.to_thread(search_comms, entity_id, time_window, None)

    # Gather results concurrently
    orders_res, trades_res, market_res, comms_res = await asyncio.gather(
        orders_task, trades_task, market_task, comms_task
    )

    merged = {}
    merged.update({k: v for k, v in orders_res.items() if k not in ("entity_id", "time_window")})
    merged.update({k: v for k, v in trades_res.items() if k not in ("entity_id", "time_window")})
    merged.update({k: v for k, v in market_res.items() if k not in ("symbol", "time_window")})
    merged.update({k: v for k, v in comms_res.items() if k not in ("entity_id", "time_window")})
    
    merged["entity_id"] = entity_id
    merged["symbol"] = symbol
    merged["time_window"] = time_window

    return merged


# ---------------------------------------------------------------------------
# write_attempt_artifacts
# ---------------------------------------------------------------------------

def _as_list(v) -> list:
    """Normalize a value that may be an int count or a list to a list."""
    if isinstance(v, list):
        return v
    return []


def _count_of(v) -> int:
    """Return count from either a list or an int."""
    if isinstance(v, int):
        return v
    if isinstance(v, list):
        return len(v)
    return 0


def write_attempt_artifacts(
    attempt_n: int,
    findings: dict[str, Any],
    refined_workflow: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Write attempt artifacts: refined YAML, multi-tab XLSX, and closure note.

    The base workflow YAML (fx_fro_surveillance.yaml) is never touched.
    This function writes attempt_N.yaml which documents what the agentic
    investigator did DIFFERENTLY from the base — expanded time windows,
    lowered thresholds, additional keywords, SOP sections invoked, etc.

    Args:
        attempt_n: The attempt number (1-indexed).
        findings: Dict containing all investigation findings from this attempt.
        refined_workflow: Optional dict from the agentic_investigator describing
            exactly what it changed vs the base workflow. If None, a default
            snapshot is built from the findings dict.

    Returns:
        Dict with paths to created files: yaml_path, xlsx_path, closure_path.
    """
    attempt_dir = Path(config.output_base_dir) / f"attempt_{attempt_n}"
    attempt_dir.mkdir(parents=True, exist_ok=True)

    # --- 1. Refined YAML — documents what THIS attempt did vs the base ---
    yaml_path = attempt_dir / f"attempt_{attempt_n}.yaml"

    # If the agentic_investigator supplied a refined_workflow dict, use it.
    # Otherwise fall back to building one from findings.
    if refined_workflow and isinstance(refined_workflow, dict):
        rw = refined_workflow
    else:
        rw = findings.get("refined_workflow", {})

    # Build the full attempt YAML
    yaml_content: dict[str, Any] = {
        "attempt": attempt_n,
        "generated_at": datetime.utcnow().isoformat() + "Z",

        # ── Identity ──────────────────────────────────────────────────────
        "entity_id": findings.get("entity_id", rw.get("entity_id", "")),
        "symbol":    findings.get("symbol",    rw.get("symbol", "")),

        # ── Escalation result for this attempt ────────────────────────────
        "escalation_score":     findings.get("escalation_score", 0.0),
        "escalation_decision":  (
            "ESCALATE"          if findings.get("escalation_score", 0.0) >= config.escalation_threshold
            else "INVESTIGATE_FURTHER" if findings.get("escalation_score", 0.0) >= 0.60
            else "MONITOR"
        ),

        # ── Reference to the constant base workflow ───────────────────────
        "base_workflow_ref": "fx_fro_surveillance.yaml",
        "investigation_type": rw.get("investigation_type", (
            "rules_based" if attempt_n == 0 else "agentic"
        )),

        # ── What the SOP told this attempt to do ─────────────────────────
        "sop_sections_invoked":         rw.get("sop_sections_invoked", []),
        "time_expansion_rules_applied": rw.get("expansion_rules_fired", []),
        "comms_categories_hit":         findings.get("comms_categories_hit", []),
        "extra_checks_performed":       rw.get("extra_checks_performed", []),

        # ── What this attempt changed vs the base workflow ─────────────────
        "refinements_from_base": {
            "time_window": {
                "base":         rw.get("time_window_base",
                                       findings.get("time_window", "")),
                "expanded_to":  rw.get("time_window_expanded",
                                       findings.get("time_window", "")),
                "expansion_reason": rw.get("expansion_reason", "base window used"),
            },
            "cancel_rate_threshold": {
                "base":    config.cancel_rate_threshold,
                "used":    rw.get("cancel_rate_threshold_used",
                                  config.cancel_rate_threshold),
            },
            "front_run_seconds": {
                "base":    config.front_run_seconds,
                "used":    rw.get("front_run_seconds_used",
                                  config.front_run_seconds),
            },
            "wash_trade_seconds": {
                "base":    config.wash_trade_seconds,
                "used":    rw.get("wash_trade_seconds_used",
                                  config.wash_trade_seconds),
            },
            "comms_keywords": {
                "base_count": 13,  # original default keyword count
                "used_count": len(rw.get("comms_keywords_used", [])),
                "keywords_used": rw.get("comms_keywords_used", []),
            },
        },

        # ── Findings delta vs previous attempt ───────────────────────────
        "findings_delta": rw.get("findings_delta", {}),

        # ── Complete findings summary ──────────────────────────────────────
        "findings_summary": {
            "orders_anomaly_score":     findings.get("orders_anomaly_score", 0.0),
            "trades_anomaly_score":     findings.get("trades_anomaly_score", 0.0),
            "market_data_anomaly_score":findings.get("market_data_anomaly_score", 0.0),
            "comms_coordination_score": findings.get("comms_coordination_score", 0.0),
            "spoofing_flag":            findings.get("spoofing_flag", False),
            "wash_trade_pairs_count":   _count_of(findings.get("wash_trade_pairs", [])),
            "front_running_signals_count": _count_of(findings.get("front_running_signals", [])),
            "comms_keyword_hits":       findings.get("comms_keyword_hits", 0),
            "narrative_score":          findings.get("narrative_score", 0.0),
            "alternative_hypotheses":   findings.get("alternative_hypotheses_considered", []),
        },
    }

    with open(yaml_path, "w") as f:
        yaml.dump(yaml_content, f, default_flow_style=False, sort_keys=False)

    # --- 2. XLSX multi-tab ---
    xlsx_path = attempt_dir / "data.xlsx"
    try:
        import openpyxl  # noqa: F401 — ensures engine is available

        with pd.ExcelWriter(str(xlsx_path), engine="openpyxl") as writer:
            # Tab: trades
            trades_records = findings.get("filtered_trades", [])
            trades_df = pd.DataFrame(trades_records) if trades_records else pd.DataFrame(columns=["trade_id"])
            trades_df.to_excel(writer, sheet_name="trades", index=False)

            # Tab: orders
            orders_records = findings.get("filtered_orders", [])
            orders_df = pd.DataFrame(orders_records) if orders_records else pd.DataFrame(columns=["order_id"])
            orders_df.to_excel(writer, sheet_name="orders", index=False)

            # Tab: front_running_book
            frb_records = _as_list(findings.get("front_running_signals", []))
            if not frb_records:
                frb_records = _as_list(findings.get("wash_trade_pairs", []))
            frb_df = pd.DataFrame(frb_records) if frb_records else pd.DataFrame(columns=["trade_id"])
            frb_df.to_excel(writer, sheet_name="front_running_book", index=False)

            # Tab: market_data
            md_records = findings.get("market_data_snapshot", [])
            md_df = pd.DataFrame(md_records) if md_records else pd.DataFrame(columns=["symbol"])
            md_df.to_excel(writer, sheet_name="market_data", index=False)

            # Tab: comms
            comms_records = findings.get("hit_details", [])
            # Normalize if LLM degraded list-of-dicts → list-of-lists
            # (LLM serialises dict values in alphabetical key order)
            if comms_records and isinstance(comms_records[0], (list, tuple)):
                _cols = ["channel", "comm_id", "content", "matched_keywords", "participants", "timestamp"]
                comms_records = [dict(zip(_cols, row)) for row in comms_records]
            comms_df = pd.DataFrame(comms_records) if comms_records else pd.DataFrame(columns=["comm_id"])
            comms_df.to_excel(writer, sheet_name="comms", index=False)

    except ImportError:
        logger.warning("openpyxl not installed; skipping XLSX creation.")
        xlsx_path = attempt_dir / "data_unavailable.txt"
        xlsx_path.write_text("Install openpyxl to generate Excel output.")

    # --- 3. Closure note ---
    closure_path = attempt_dir / "closure_note.txt"
    score = findings.get("escalation_score", 0.0)
    reasoning = findings.get("reasoning", "No reasoning provided.")
    entity = findings.get("entity_id", rw.get("entity_id", "Unknown"))
    symbol = findings.get("symbol", rw.get("symbol", "Unknown"))
    tw_base = rw.get("time_window_base", findings.get("time_window", "Unknown"))
    tw_expanded = rw.get("time_window_expanded", tw_base)
    investigation_type = rw.get("investigation_type", "rules_based" if attempt_n == 0 else "agentic")

    decision = (
        "ESCALATE"            if score >= config.escalation_threshold
        else "INVESTIGATE FURTHER" if score >= 0.60
        else "MONITOR"
    )

    closure_lines = [
        f"FX-FRO SURVEILLANCE CLOSURE NOTE — Attempt {attempt_n}",
        "=" * 60,
        f"Timestamp         : {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
        f"Entity            : {entity}",
        f"Symbol            : {symbol}",
        f"Investigation Type: {investigation_type}",
        f"Base Window       : {tw_base}",
        f"Expanded Window   : {tw_expanded}",
        f"Escalation Score  : {score:.2f}",
        f"Decision          : {decision}",
        "",
        "SOP PROCEDURE FOLLOWED",
        "-" * 40,
    ]
    for s in rw.get("sop_sections_invoked", []):
        closure_lines.append(f"  [x] {s}")
    if not rw.get("sop_sections_invoked"):
        closure_lines.append("  (rules-based phase — SOP not yet invoked)")

    closure_lines += [
        "",
        "TIME WINDOW EXPANSION",
        "-" * 40,
        f"  Base    : {tw_base}",
        f"  Expanded: {tw_expanded}",
    ]
    for rule in rw.get("expansion_rules_fired", []):
        closure_lines.append(f"  Rule fired: {rule}")

    closure_lines += [
        "",
        "FINDINGS SUMMARY",
        "-" * 40,
        f"  Orders Anomaly Score    : {findings.get('orders_anomaly_score', 0.0):.2f}",
        f"  Trades Anomaly Score    : {findings.get('trades_anomaly_score', 0.0):.2f}",
        f"  Market Data Anomaly     : {findings.get('market_data_anomaly_score', 0.0):.2f}",
        f"  Comms Coordination Score: {findings.get('comms_coordination_score', 0.0):.2f}",
        f"  Spoofing Flag           : {findings.get('spoofing_flag', False)}",
        f"  Wash Trade Pairs        : {_count_of(findings.get('wash_trade_pairs', []))}",
        f"  Front-Running Signals   : {_count_of(findings.get('front_running_signals', []))}",
        f"  Comms Keyword Hits      : {findings.get('comms_keyword_hits', 0)}",
        f"  Narrative Score (Sec 8.2): {findings.get('narrative_score', 0.0):.2f}",
        "",
        "COMMS KEYWORD CATEGORIES HIT",
        "-" * 40,
    ]
    for cat in findings.get("comms_categories_hit", []):
        closure_lines.append(f"  [!] {cat}")
    if not findings.get("comms_categories_hit"):
        closure_lines.append("  None")

    closure_lines += [
        "",
        "ALTERNATIVE HYPOTHESES CONSIDERED",
        "-" * 40,
    ]
    for hyp in findings.get("alternative_hypotheses_considered", []):
        closure_lines.append(f"  - {hyp}")
    if not findings.get("alternative_hypotheses_considered"):
        closure_lines.append("  None documented")

    closure_lines += [
        "",
        "REASONING",
        "-" * 40,
        reasoning,
        "",
        "FOLLOW-UP QUERIES FOR NEXT CYCLE",
        "-" * 40,
    ]
    for q in findings.get("follow_up_queries", []):
        closure_lines.append(f"  - {q}")
    if not findings.get("follow_up_queries"):
        closure_lines.append("  None (investigation complete or escalated)")

    if score >= config.escalation_threshold:
        closure_lines += [
            "",
            "=" * 60,
            "*** ESCALATED: Score meets or exceeds threshold (0.80). ***",
            "*** Refer immediately to Compliance for formal review.  ***",
            "=" * 60,
        ]

    closure_path.write_text("\n".join(closure_lines))

    return {
        "yaml_path": str(yaml_path),
        "xlsx_path": str(xlsx_path),
        "closure_path": str(closure_path),
        "attempt_dir": str(attempt_dir),
    }
