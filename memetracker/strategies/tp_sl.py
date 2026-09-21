from __future__ import annotations

from memetracker.models import PriceSnapshot
from memetracker.strategies.base import BaseStrategy, LOSS, WIN


class TakeProfit2xStopLoss30(BaseStrategy):
    name = "tp_2x_sl_30"

    def evaluate(self, snapshot: PriceSnapshot) -> None:
        if snapshot.price_usd >= self.result.entry_price * 2:
            self.finish(snapshot, WIN)
            self.state["reason"] = "take_profit"
        elif snapshot.price_usd <= self.result.entry_price * 0.70:
            self.finish(snapshot, LOSS)
            self.state["reason"] = "stop_loss"

