from __future__ import annotations
from signals.base import BaseSignal
from engine.payload import NodePayload, Signal

class SpreadWideningSignal(BaseSignal):
    id    = "spread_widening_post_trade"
    label = "Spread Widening Post-Trade"
    default_threshold = 0.4

    def evaluate(self, inputs: dict[str, NodePayload], params: dict) -> Signal:
        market_payload = inputs.get("market_data_fetcher")
        trades_payload = inputs.get("trade_extractor")

        if not market_payload or not trades_payload or not market_payload.rows:
            return Signal(id=self.id, label=self.label, triggered=False, score=0.0,
                          evidence={"reason": "missing market or trade data"})

        market_rows = sorted(market_payload.rows, key=lambda r: r.get("timestamp", ""))

        # Split market ticks into pre-trade and post-trade halves
        mid = len(market_rows) // 2
        pre_rows  = market_rows[:mid] if mid > 0 else market_rows
        post_rows = market_rows[mid:] if mid > 0 else []

        def avg_spread(rows):
            spreads = []
            for r in rows:
                ask = float(r.get("ask", 0) or 0)
                bid = float(r.get("bid", 0) or 0)
                if ask > 0 and bid > 0:
                    spreads.append(ask - bid)
            return sum(spreads) / len(spreads) if spreads else 0.0

        pre_spread  = avg_spread(pre_rows)
        post_spread = avg_spread(post_rows)

        if pre_spread <= 0:
            return Signal(id=self.id, label=self.label, triggered=False, score=0.0,
                          evidence={"reason": "could not compute pre-trade spread"})

        widening_pct = (post_spread - pre_spread) / pre_spread * 100
        threshold_pct = float(params.get("spread_widening_threshold_pct", 5.0))
        triggered = widening_pct >= threshold_pct
        score     = min(1.0, widening_pct / 30.0) if triggered else 0.0

        return Signal(
            id=self.id, label=self.label,
            triggered=triggered, score=score,
            threshold=self.default_threshold,
            evidence={
                "pre_trade_avg_spread_bps":  round(pre_spread * 10000, 2),
                "post_trade_avg_spread_bps": round(post_spread * 10000, 2),
                "widening_pct":              round(widening_pct, 2),
                "threshold_pct":             threshold_pct,
            }
        )
