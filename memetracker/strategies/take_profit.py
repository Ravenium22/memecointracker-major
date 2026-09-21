from __future__ import annotations

from memetracker.models import PriceSnapshot
from memetracker.strategies.base import BaseStrategy, WIN


class TakeProfit2x(BaseStrategy):
    name = "take_profit_2x"

    def evaluate(self, snapshot: PriceSnapshot) -> None:
        if snapshot.price_usd >= self.result.entry_price * 2:
            self.finish(snapshot, WIN)

