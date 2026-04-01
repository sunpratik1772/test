from __future__ import annotations
from signals.comms_keyword import CommsKeywordSignal
from signals.trade_ahead    import TradeAheadOfMarketSignal
from signals.spread_widening import SpreadWideningSignal
from signals.book_benefited  import BookBenefitedSignal

SIGNAL_REGISTRY: dict = {
    "comms_keyword":             CommsKeywordSignal(),
    "trade_ahead_of_market":     TradeAheadOfMarketSignal(),
    "spread_widening_post_trade": SpreadWideningSignal(),
    "book_benefited":            BookBenefitedSignal(),
}

def get_signal(signal_id: str):
    sig = SIGNAL_REGISTRY.get(signal_id)
    if not sig:
        raise ValueError(f"Unknown signal: {signal_id}")
    return sig
