from __future__ import annotations

from datetime import timedelta

from memetracker.models import PriceSnapshot
from memetracker.strategies.base import BaseStrategy, FINISHED, WIN, LOSS
from memetracker.strategies.base import roi_percent


class HoldStrategy(BaseStrategy):
    hold_seconds: int = 0
    name = "hold"

    def evaluate(self, snapshot: PriceSnapshot) -> None:
        target = self.call.call_timestamp + timedelta(seconds=self.hold_seconds)
        if snapshot.timestamp >= target:
            status = WIN if roi_percent(self.result.entry_price, snapshot.price_usd) > 0 else LOSS
            self.finish(snapshot, status)


class Hold5m(HoldStrategy):
    name = "hold_5m"
    hold_seconds = 5 * 60


class Hold15m(HoldStrategy):
    name = "hold_15m"
    hold_seconds = 15 * 60


class Hold30m(HoldStrategy):
    name = "hold_30m"
    hold_seconds = 30 * 60


class Hold1h(HoldStrategy):
    name = "hold_1h"
    hold_seconds = 60 * 60

