from __future__ import annotations
import re
from signals.base import BaseSignal
from engine.payload import NodePayload, Signal

DEFAULT_KEYWORDS = [
    "sell it off", "sell off", "get out", "dump it", "dump", "get rid",
    "before market", "move quickly", "quickly", "client wants to sell",
    "unload", "offload", "clear it", "clear position"
]

class CommsKeywordSignal(BaseSignal):
    id    = "comms_keyword"
    label = "Suspicious Comms Keywords"
    default_threshold = 0.3

    def evaluate(self, inputs: dict[str, NodePayload], params: dict) -> Signal:
        comms_payload = inputs.get("comms_search")
        if not comms_payload or not comms_payload.rows:
            return Signal(id=self.id, label=self.label, triggered=False, score=0.0, evidence={"reason": "no comms data"})

        keywords = params.get("keywords", DEFAULT_KEYWORDS)
        pattern  = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)

        hits = []
        for row in comms_payload.rows:
            content = row.get("content_summary", "") + " " + row.get("flagged_keywords", "")
            matches = pattern.findall(content)
            if matches:
                hits.append({
                    "timestamp":  row.get("timestamp"),
                    "channel":    row.get("channel"),
                    "matches":    list(set(m.lower() for m in matches)),
                    "content":    row.get("content_summary", "")[:120],
                })

        triggered = len(hits) > 0
        score     = min(1.0, len(hits) * 0.4)
        return Signal(
            id=self.id, label=self.label,
            triggered=triggered, score=score,
            threshold=self.default_threshold,
            evidence={
                "hit_count":     len(hits),
                "keywords_found": list({m for h in hits for m in h["matches"]}),
                "comms_hits":    hits,
            }
        )
