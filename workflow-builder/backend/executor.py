"""
Workflow executor — walks a serialised workflow graph node-by-node,
calls Gemini for the AI Summary node, and yields SSE-style events.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from typing import Any

import certifi

_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gemini_call(prompt: str, model: str, api_key: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/{model}:generateContent?key={api_key}"
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 1024},
    }).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        body = json.loads(resp.read())
        return body["candidates"][0]["content"]["parts"][0]["text"]


def _topological_sort(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Return nodes in dependency order (sources first)."""
    id_to_node = {n["id"]: n for n in nodes}
    in_edges: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        in_edges[e["target"]].append(e["source"])

    visited: set[str] = set()
    order: list[dict] = []

    def visit(nid: str) -> None:
        if nid in visited:
            return
        for dep in in_edges[nid]:
            visit(dep)
        visited.add(nid)
        order.append(id_to_node[nid])

    for n in nodes:
        visit(n["id"])
    return order


# ---------------------------------------------------------------------------
# Simulated per-node execution
# ---------------------------------------------------------------------------

_NODE_DELAYS: dict[str, float] = {
    "trigger":                    0.3,
    "order_collector":            0.8,
    "book_collector":             0.8,
    "market_collector":           0.7,
    "comms_collector":            0.6,
    "fi_auction_collector":       0.5,
    "counterparty_collector":     0.5,
    "order_extractor":            0.4,
    "book_extractor":             0.4,
    "market_extractor":           0.4,
    "fi_order_extractor":         0.4,
    "fi_execution_extractor":     0.4,
    "wash_trade_extractor":       0.4,
    "order_lifecycle_analyser":   0.6,
    "trade_metrics_analyser":     0.6,
    "fi_otr_analyser":            0.5,
    "fi_cancel_latency_analyser": 0.4,
    "fi_yield_displacement_analyser": 0.5,
    "fi_book_imbalance_analyser": 0.4,
    "fi_directional_reversal_analyser": 0.4,
    "fi_auction_analyser":        0.4,
    "wash_pair_detector":         0.7,
    "volume_inflation_analyser":  0.4,
    "price_marking_analyser":     0.4,
    "indicator_filter":           0.5,
    "routing_engine":             0.3,
    "summary_builder":            0.5,
    "ai_summary":                 3.0,   # real Gemini call
    "excel_builder":              1.0,
    "audit_record":               0.4,
}


def _mock_node_output(node_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """Return plausible mock output for every node type."""
    alert_type = config.get("alert_type", "fx_front_running")
    trader_id  = config.get("trader_id", "TRADER_001")

    defaults: dict[str, Any] = {
        "trigger": {
            "alert_id": config.get("alert_id", "FRO-001"),
            "alert_type": alert_type,
            "trader_id": trader_id,
            "instrument": config.get("instrument", "EUR/USD"),
            "window_minutes": config.get("window_minutes", 60),
        },
        "order_collector":   {"rows": 42, "status": "OK"},
        "book_collector":    {"rows": 18, "status": "OK"},
        "market_collector":  {"rows": 120, "status": "OK"},
        "comms_collector":   {"rows": 7,  "status": "OK"},
        "fi_auction_collector":    {"rows": 1, "status": "OK"},
        "counterparty_collector":  {"rows": 3, "status": "OK"},
        "order_extractor":   {"record_count": 42, "status": "OK"},
        "book_extractor":    {"record_count": 18, "status": "OK"},
        "market_extractor":  {"record_count": 120, "status": "OK"},
        "fi_order_extractor":      {"record_count": 38, "status": "OK"},
        "fi_execution_extractor":  {"record_count": 14, "status": "OK"},
        "wash_trade_extractor":    {"record_count": 22, "status": "OK"},
        "order_lifecycle_analyser": {
            "initial_qty": 5000000,
            "total_filled": 4800000,
            "duration": "0 days, 0 hours, 12 minutes, 33.420 seconds",
            "status": "partially filled",
        },
        "trade_metrics_analyser": {
            "before_count": 3, "during_count": 11, "after_count": 4,
        },
        "fi_otr_analyser": {
            "otr_per_tenor": {"2yr": 2.1, "5yr": 18.4, "10yr": 6.3},
            "overall_otr_dv01_normalised": 8.9,
        },
        "fi_cancel_latency_analyser": {"latency_ms": 35, "sample_size": 22},
        "fi_yield_displacement_analyser": {
            "pre_yield": 4.21, "peak_yield": 4.18,
            "displacement_bps": 3.0, "direction": "BID",
        },
        "fi_book_imbalance_analyser": {"imbalance": 4.2, "dominant_side": "BID"},
        "fi_directional_reversal_analyser": {"reversal": True},
        "fi_auction_analyser": {
            "auction_imminent": False, "minutes_to_auction": None,
            "otr_adjustment_factor": 1.0,
        },
        "wash_pair_detector": {
            "pair_count": 3,
            "avg_quantity_match": 0.012,
            "avg_price_match": 3.2,
            "avg_time_delta": 2.4,
        },
        "volume_inflation_analyser": {
            "total_wash_volume": 15000000, "wash_volume_pct": 12.3,
        },
        "price_marking_analyser": {"near_eod": True, "near_fixing": False},
        "indicator_filter": {
            "flag_count": 4,
            "flags": {
                "direction_match": True,
                "fr_window_seconds": False,
                "otr": False,
                "cancel_latency_ms": True,
                "price_favoured_trader": True,
                "price_move_bps": False,
                "pnl_bps": True,
                "fresh_position": False,
                "exemption_scope": False,
                "active_investigation": False,
                "fr_book_identified": False,
            },
        },
        "routing_engine": {"disposition": "HUMAN REVIEW", "flag_count": 4},
        "summary_builder": {
            "order_lifecycle_sentence": (
                "A TWAP order for 5,000,000 EUR/USD was placed using TWAP strategy "
                "in EUR/USD which lasted for 0 days, 0 hours, 12 minutes, 33.420 seconds "
                "with partially filled."
            ),
            "trade_metrics_sentence": (
                "11 trades were observed in EUR/USD on the FX_PROP book "
                "during the focus order submission period."
            ),
        },
        "ai_summary": {"memo": "-- AI memo will appear here --", "defensibility": "WEAKLY_DEFENSIBLE"},
        "excel_builder": {"excel_path": "results/FRO-001_report.xlsx"},
        "audit_record":  {"audit_path": "results/FRO-001_audit.json"},
    }
    return defaults.get(node_type, {"status": "OK"})


# ---------------------------------------------------------------------------
# Public generator
# ---------------------------------------------------------------------------

Event = dict[str, Any]


def execute_workflow(
    workflow: dict[str, Any],
    api_key: str,
) -> Generator[Event, None, None]:
    """
    Walk the workflow graph and yield events:
      {"type": "node_start",    "node_id": ..., "label": ...}
      {"type": "node_complete", "node_id": ..., "label": ..., "output": {...}}
      {"type": "node_error",    "node_id": ..., "label": ..., "error": "..."}
      {"type": "workflow_done", "disposition": ..., "flag_count": ...}
    """
    nodes: list[dict] = workflow.get("nodes", [])
    edges: list[dict] = workflow.get("edges", [])

    if not nodes:
        yield {"type": "workflow_done", "disposition": "N/A", "flag_count": 0, "error": "No nodes in workflow"}
        return

    ordered = _topological_sort(nodes, edges)

    # Shared context accumulates outputs across nodes
    ctx: dict[str, Any] = {}
    disposition = "CLOSE"
    flag_count = 0

    for node in ordered:
        nid    = node["id"]
        ntype  = node.get("data", {}).get("type", "")
        label  = node.get("data", {}).get("label", ntype)
        config = {**ctx, **node.get("data", {}).get("config", {})}

        yield {"type": "node_start", "node_id": nid, "label": label}

        delay = _NODE_DELAYS.get(ntype, 0.5)

        try:
            if ntype == "ai_summary":
                # Real Gemini call
                model = config.get("model", "gemini-2.5-flash")
                flags = ctx.get("flags", {})
                disp  = ctx.get("disposition", "UNKNOWN")
                prompt = (
                    f"You are a senior surveillance analyst.\n"
                    f"Alert type: {config.get('alert_type', 'unknown')}\n"
                    f"Disposition: {disp}\n"
                    f"Indicator flags: {json.dumps(flags, indent=2)}\n\n"
                    f"Write a concise 3-section memo (max {config.get('max_words', 300)} words):\n"
                    f"1. FINDINGS: What the data shows\n"
                    f"2. WHAT WAS RULED OUT: Alternatives tested and eliminated\n"
                    f"3. DEFENSIBILITY FLAG: one of DEFENSIBLE / WEAKLY_DEFENSIBLE / NOT_DEFENSIBLE "
                    f"with one-sentence justification.\n"
                    f"Do not assign a final disposition."
                )
                memo_text = _gemini_call(prompt, model, api_key)
                defensibility = (
                    "NOT_DEFENSIBLE"   if "NOT_DEFENSIBLE"   in memo_text else
                    "WEAKLY_DEFENSIBLE" if "WEAKLY_DEFENSIBLE" in memo_text else
                    "DEFENSIBLE"
                )
                output = {"memo": memo_text, "defensibility": defensibility}
            else:
                time.sleep(delay)
                output = _mock_node_output(ntype, config)

            # Bubble up key values into shared context
            if ntype == "trigger":
                ctx.update(output)
            if ntype == "indicator_filter":
                ctx["flag_count"] = output.get("flag_count", 0)
                ctx["flags"]      = output.get("flags", {})
                flag_count        = output.get("flag_count", 0)
            if ntype == "routing_engine":
                ctx["disposition"] = output.get("disposition", "CLOSE")
                disposition        = output.get("disposition", "CLOSE")

            yield {"type": "node_complete", "node_id": nid, "label": label, "output": output}

        except Exception as exc:
            yield {"type": "node_error", "node_id": nid, "label": label, "error": str(exc)}

    yield {"type": "workflow_done", "disposition": disposition, "flag_count": flag_count}
