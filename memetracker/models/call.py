from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ParsedCall:
    ticker: str | None
    contract_address: str
    market_cap_from_message: float | None
    token_age: str | None
    net_buy: float | None
    kol_count: int | None
    discord_message_id: int
    discord_timestamp: datetime
    discord_author: str


@dataclass(slots=True)
class Call:
    id: int
    discord_message_id: int
    ticker: str | None
    contract_address: str
    call_timestamp: datetime
    mc_message: float | None
    token_age: str | None
    net_buy: float | None
    kol_count: int | None
    entry_price: float
    entry_market_cap: float | None
    entry_liquidity: float | None
    pair_address: str | None
    dex_id: str | None
    created_at: datetime

