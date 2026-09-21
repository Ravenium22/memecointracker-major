from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class PriceSnapshot:
    contract_address: str
    timestamp: datetime
    price_usd: float
    market_cap: float | None
    fdv: float | None
    liquidity_usd: float | None
    volume_24h: float | None

