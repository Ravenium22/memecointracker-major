from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class StrategyResult:
    call_id: int
    strategy_name: str
    status: str
    entry_price: float
    exit_price: float | None = None
    exit_timestamp: datetime | None = None
    roi_percent: float | None = None
    max_roi_percent: float = 0.0
    max_drawdown_percent: float = 0.0
    duration_seconds: int | None = None
    metadata_json: str = "{}"

