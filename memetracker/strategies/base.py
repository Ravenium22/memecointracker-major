from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from memetracker.models import Call, PriceSnapshot, StrategyResult


OPEN = "OPEN"
WIN = "WIN"
LOSS = "LOSS"
EXPIRED = "EXPIRED"
FINISHED = "FINISHED"


class BaseStrategy(ABC):
    name: str

    def __init__(self, call: Call, existing: StrategyResult | None = None) -> None:
        self.call = call
        self.result = existing or StrategyResult(
            call_id=call.id,
            strategy_name=self.name,
            status=OPEN,
            entry_price=call.entry_price,
        )
        self.state: dict[str, Any] = self._load_state(self.result.metadata_json)

    def on_call(self) -> StrategyResult:
        self.result.metadata_json = self._dump_state()
        return self.result

    def on_price_update(self, snapshot: PriceSnapshot) -> StrategyResult:
        if self.is_finished() or snapshot.timestamp < self.call.call_timestamp:
            return self.result
        self._update_extremes(snapshot.price_usd)
        self.evaluate(snapshot)
        self.result.metadata_json = self._dump_state()
        return self.result

    def is_finished(self) -> bool:
        return self.result.status in {WIN, LOSS, EXPIRED, FINISHED}

    def expire(self, timestamp: datetime) -> StrategyResult:
        if not self.is_finished():
            self.result.status = EXPIRED
            self.result.exit_timestamp = timestamp
            self.result.duration_seconds = int((timestamp - self.call.call_timestamp).total_seconds())
            self.result.metadata_json = self._dump_state()
        return self.result

    @abstractmethod
    def evaluate(self, snapshot: PriceSnapshot) -> None:
        raise NotImplementedError

    def finish(self, snapshot: PriceSnapshot, status: str) -> None:
        roi = roi_percent(self.result.entry_price, snapshot.price_usd)
        self.result.status = status
        self.result.exit_price = snapshot.price_usd
        self.result.exit_timestamp = snapshot.timestamp
        self.result.roi_percent = roi
        self.result.duration_seconds = int((snapshot.timestamp - self.call.call_timestamp).total_seconds())

    def _update_extremes(self, price: float) -> None:
        roi = roi_percent(self.result.entry_price, price)
        self.result.max_roi_percent = max(self.result.max_roi_percent, roi)
        self.result.max_drawdown_percent = min(self.result.max_drawdown_percent, roi)

    def _load_state(self, raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _dump_state(self) -> str:
        return json.dumps(self.state, separators=(",", ":"), sort_keys=True)


def roi_percent(entry_price: float, price: float) -> float:
    if entry_price <= 0:
        return 0.0
    return ((price / entry_price) - 1) * 100

