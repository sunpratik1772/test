from __future__ import annotations
import csv, os, time
from datetime import datetime, timedelta
from engine.payload import NodePayload

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

def _parse_dt(s: str):
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(s).strip(), fmt)
        except ValueError:
            continue
    return None

def handle(node_id: str, config: dict, inputs: dict[str, NodePayload], params: dict) -> NodePayload:
    t0 = time.time()
    comms = inputs.get("comms_search")

    # Derive context from upstream comms
    trader_id   = (comms.metadata.get("trader_id") if comms else None) or params.get("trader_id", "")
    time_window = (comms.metadata.get("time_window") if comms else {}) or {}

    # Widen window: look +-15 min around comms window
    window_buffer_min = int(params.get("window_buffer_minutes", 15))
    start_dt = end_dt = None
    if time_window.get("start"):
        start_dt = _parse_dt(time_window["start"])
        if start_dt:
            start_dt -= timedelta(minutes=window_buffer_min)
    if time_window.get("end"):
        end_dt = _parse_dt(time_window["end"])
        if end_dt:
            end_dt += timedelta(minutes=window_buffer_min)

    path = os.path.join(DATA_DIR, "trades.csv")
    rows = []

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if trader_id and row.get("trader_id") != trader_id:
                continue
            if row.get("trade_type", "").upper() != "PROP":
                continue
            t = _parse_dt(row.get("trade_time", ""))
            if start_dt and t and t < start_dt:
                continue
            if end_dt and t and t > end_dt:
                continue
            rows.append(dict(row))

    instruments = list({r.get("instrument") for r in rows if r.get("instrument")})
    total_notional = sum(float(r.get("quantity", 0) or 0) for r in rows)

    return NodePayload(
        node_id=node_id, node_type="source", label="Trade Extractor",
        rows=rows, row_count=len(rows),
        summary_text=f"Found {len(rows)} prop trade(s) for {trader_id} "
                     f"in window {time_window.get('start','?')} - {time_window.get('end','?')} "
                     f"(+-{window_buffer_min}min). Instruments: {', '.join(instruments)}. "
                     f"Total notional: {total_notional:,.0f}",
        filters_applied={"trader_id": trader_id, "time_window": time_window, "trade_type": "PROP"},
        execution_ms=int((time.time()-t0)*1000),
        metadata={
            "trader_id":       trader_id,
            "instruments":     instruments,
            "total_notional":  total_notional,
            "time_window":     time_window,
            "window_start":    str(start_dt) if start_dt else "",
            "window_end":      str(end_dt) if end_dt else "",
        }
    )
