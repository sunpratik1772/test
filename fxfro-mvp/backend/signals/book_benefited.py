from __future__ import annotations
from signals.base import BaseSignal
from engine.payload import NodePayload, Signal

class BookBenefitedSignal(BaseSignal):
    id    = "book_benefited"
    label = "Prop Book Benefited from Move"
    default_threshold = 0.5

    def evaluate(self, inputs: dict[str, NodePayload], params: dict) -> Signal:
        book_payload   = inputs.get("book_activity")
        market_payload = inputs.get("market_data_fetcher")

        if not book_payload or not market_payload:
            return Signal(id=self.id, label=self.label, triggered=False, score=0.0,
                          evidence={"reason": "missing book or market data"})

        pnl_impact = float(book_payload.metadata.get("estimated_pnl_usd", 0) or 0)
        triggered  = pnl_impact > 0
        score      = min(1.0, pnl_impact / 100_000) if triggered else 0.0

        return Signal(
            id=self.id, label=self.label,
            triggered=triggered, score=score,
            threshold=self.default_threshold,
            evidence={
                "estimated_pnl_usd":      round(pnl_impact, 2),
                "prop_trade_count":       book_payload.metadata.get("prop_trade_count", 0),
                "prop_sell_notional_usd": book_payload.metadata.get("prop_sell_notional_usd", 0),
                "price_entry_avg":        book_payload.metadata.get("price_entry_avg", 0),
                "price_current":          book_payload.metadata.get("price_current", 0),
            }
        )
