from __future__ import annotations
from datetime import datetime, timedelta
from signals.base import BaseSignal
from engine.payload import NodePayload, Signal

def _parse_dt(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(str(s).strip(), fmt)
        except ValueError:
            continue
    return None

class TradeAheadOfMarketSignal(BaseSignal):
    id    = "trade_ahead_of_market"
    label = "Prop Trades Ahead of Market Move"
    default_threshold = 0.5

    def evaluate(self, inputs: dict[str, NodePayload], params: dict) -> Signal:
        trades_payload = inputs.get("trade_extractor")
        market_payload = inputs.get("market_data_fetcher")

        if not trades_payload or not market_payload:
            return Signal(id=self.id, label=self.label, triggered=False, score=0.0,
                          evidence={"reason": "missing trades or market data"})

        # Find when the significant price drop started
        market_rows = sorted(market_payload.rows, key=lambda r: r.get("timestamp", ""))
        if len(market_rows) < 3:
            return Signal(id=self.id, label=self.label, triggered=False, score=0.0,
                          evidence={"reason": "insufficient market data"})

        # Compute price movement between each tick — find first significant drop
        move_threshold_bps = float(params.get("min_movement_bps", 5))
        move_start_time    = None
        move_bps           = 0.0
        for i in range(1, len(market_rows)):
            prev_mid = float(market_rows[i-1].get("mid", 0) or 0)
            curr_mid = float(market_rows[i].get("mid", 0) or 0)
            if prev_mid <= 0:
                continue
            bps_change = abs((curr_mid - prev_mid) / prev_mid) * 10000
            if bps_change >= move_threshold_bps:
                move_start_time = _parse_dt(market_rows[i].get("timestamp", ""))
                move_bps = bps_change
                break

        if not move_start_time:
            return Signal(id=self.id, label=self.label, triggered=False, score=0.0,
                          evidence={"reason": f"no price move >= {move_threshold_bps}bps found"})

        # Check if any prop trade was in the direction of the move BEFORE the move
        delta_seconds = int(params.get("delta_seconds", 300))   # 5 min window
        early_window_start = move_start_time - timedelta(seconds=delta_seconds)

        trades_before = []
        for row in trades_payload.rows:
            t = _parse_dt(row.get("trade_time", ""))
            if not t:
                continue
            direction = row.get("direction", "").upper()
            # Market dropped -> look for SELL trades before the drop
            if early_window_start <= t < move_start_time and direction == "SELL":
                trades_before.append({
                    "trade_id":  row.get("trade_id"),
                    "time":      str(t),
                    "direction": direction,
                    "quantity":  row.get("quantity"),
                    "price":     row.get("price"),
                    "seconds_before_move": int((move_start_time - t).total_seconds()),
                })

        triggered = len(trades_before) > 0
        score = min(1.0, len(trades_before) * 0.5) if triggered else 0.0
        return Signal(
            id=self.id, label=self.label,
            triggered=triggered, score=score,
            threshold=self.default_threshold,
            evidence={
                "market_move_start":     str(move_start_time),
                "market_move_bps":       round(move_bps, 2),
                "look_back_seconds":     delta_seconds,
                "trades_before_move":    trades_before,
                "trade_count":           len(trades_before),
            }
        )
