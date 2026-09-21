from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp


log = logging.getLogger(__name__)


@dataclass(slots=True)
class MarketData:
    contract_address: str
    pair_address: str | None
    dex_id: str | None
    base_token: dict[str, Any] | None
    quote_token: dict[str, Any] | None
    price_usd: float
    liquidity_usd: float | None
    volume_24h: float | None
    price_change_5m: float | None
    price_change_1h: float | None
    fdv: float | None
    market_cap: float | None
    pair_created_at: int | None


class DexScreenerClient:
    def __init__(self, base_url: str = "https://api.dexscreener.com", timeout_seconds: int = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "DexScreenerClient":
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def start(self) -> None:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=self.timeout)

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_token_pairs(self, contract_address: str) -> list[dict[str, Any]]:
        await self.start()
        assert self.session is not None
        url = f"{self.base_url}/tokens/v1/solana/{contract_address}"
        for attempt in range(4):
            try:
                async with self.session.get(url) as response:
                    if response.status == 429:
                        wait = 2**attempt
                        log.warning("[DEX] HTTP 429, retrying in %ss", wait)
                        await asyncio.sleep(wait)
                        continue
                    response.raise_for_status()
                    data = await response.json()
                    return data if isinstance(data, list) else data.get("pairs", [])
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                wait = min(2**attempt, 8)
                log.warning("[ERROR] DexScreener request failed: %s; retrying in %ss", exc, wait)
                await asyncio.sleep(wait)
        return []

    def select_best_pair(self, pairs: list[dict[str, Any]]) -> dict[str, Any] | None:
        solana_pairs = [
            pair
            for pair in pairs
            if pair.get("chainId") == "solana" and safe_float(pair.get("liquidity", {}).get("usd")) is not None
        ]
        if not solana_pairs:
            return None
        return max(solana_pairs, key=lambda pair: safe_float(pair.get("liquidity", {}).get("usd")) or 0.0)

    async def get_current_market_data(self, contract_address: str) -> MarketData | None:
        pairs = await self.get_token_pairs(contract_address)
        pair = self.select_best_pair(pairs)
        if not pair:
            return None
        price = safe_float(pair.get("priceUsd"))
        if price is None:
            return None
        liquidity = pair.get("liquidity") or {}
        volume = pair.get("volume") or {}
        price_change = pair.get("priceChange") or {}
        log.debug("[DEX] pair found %s %s", pair.get("dexId"), pair.get("pairAddress"))
        return MarketData(
            contract_address=contract_address,
            pair_address=pair.get("pairAddress"),
            dex_id=pair.get("dexId"),
            base_token=pair.get("baseToken"),
            quote_token=pair.get("quoteToken"),
            price_usd=price,
            liquidity_usd=safe_float(liquidity.get("usd")),
            volume_24h=safe_float(volume.get("h24")),
            price_change_5m=safe_float(price_change.get("m5")),
            price_change_1h=safe_float(price_change.get("h1")),
            fdv=safe_float(pair.get("fdv")),
            market_cap=safe_float(pair.get("marketCap")),
            pair_created_at=pair.get("pairCreatedAt"),
        )


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

