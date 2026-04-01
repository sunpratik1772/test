from __future__ import annotations
import csv, os, time
from engine.payload import NodePayload

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

def handle(node_id: str, config: dict, inputs: dict[str, NodePayload], params: dict) -> NodePayload:
    t0 = time.time()
    trades = inputs.get("trade_extractor")

    instruments  = (trades.metadata.get("instruments") if trades else None) or params.get("instruments", ["EUR/USD"])
    window_start = (trades.metadata.get("window_start") if trades else None) or ""
    window_end   = (trades.metadata.get("window_end") if trades else None) or ""

    path = os.path.join(DATA_DIR, "market_data.csv")
    rows = []

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if instruments and row.get("instrument") not in instruments:
                continue
            ts = row.get("timestamp", "")
            if window_start and ts < window_start[:19]:
                continue
            if window_end and ts > window_end[:19]:
                continue
            rows.append(dict(row))

    # Compute price movement
    price_before = price_after = movement_bps = 0.0
    if rows:
        sorted_rows = sorted(rows, key=lambda r: r.get("timestamp", ""))
        price_before = float(sorted_rows[0].get("mid", 0) or 0)
        price_after  = float(sorted_rows[-1].get("mid", 0) or 0)
        if price_before > 0:
            movement_bps = (price_after - price_before) / price_before * 10000

    return NodePayload(
        node_id=node_id, node_type="source", label="Market Data Fetcher",
        rows=rows, row_count=len(rows),
        summary_text=f"{len(rows)} market tick(s) for {', '.join(instruments)}. "
                     f"Price: {price_before:.5f} -> {price_after:.5f} "
                     f"({movement_bps:+.1f}bps)",
        filters_applied={"instruments": instruments, "window_start": window_start, "window_end": window_end},
        execution_ms=int((time.time()-t0)*1000),
        metadata={
            "instruments":   instruments,
            "price_before":  price_before,
            "price_after":   price_after,
            "movement_bps":  round(movement_bps, 2),
        }
    )
