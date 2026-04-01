from __future__ import annotations
import csv, os, re, time
from engine.payload import NodePayload

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

def handle(node_id: str, config: dict, inputs: dict[str, NodePayload], params: dict) -> NodePayload:
    t0 = time.time()
    trader_id = params.get("trader_id") or config.get("trader_id", "")
    keywords  = params.get("keywords") or config.get("keywords", [
        "sell it off", "sell off", "get out", "dump", "before market",
        "move quickly", "quickly", "client wants to sell", "unload"
    ])
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",")]

    pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
    path    = os.path.join(DATA_DIR, "comms.csv")
    rows    = []

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if trader_id and row.get("trader_id") != trader_id:
                continue
            content = row.get("content_summary", "") + " " + row.get("flagged_keywords", "")
            if pattern.search(content):
                rows.append(dict(row))

    # Derive time window from matched comms
    timestamps = sorted(r.get("timestamp", "") for r in rows if r.get("timestamp"))
    time_window = {"start": timestamps[0], "end": timestamps[-1]} if timestamps else {}
    instruments = list({r.get("instrument_mentioned", "") for r in rows if r.get("instrument_mentioned")})

    return NodePayload(
        node_id=node_id, node_type="source", label="Comms Search",
        rows=rows, row_count=len(rows),
        summary_text=f"Found {len(rows)} flagged communication(s) for {trader_id or 'all traders'} "
                     f"matching keywords: {', '.join(keywords[:3])}{'...' if len(keywords)>3 else ''}",
        filters_applied={"trader_id": trader_id, "keywords": keywords},
        execution_ms=int((time.time()-t0)*1000),
        metadata={
            "trader_id":            trader_id,
            "time_window":          time_window,
            "instruments_mentioned": instruments,
        }
    )
