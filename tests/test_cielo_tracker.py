from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from memetracker.database import Database
from memetracker.market.tracker import CieloAlertTracker
from memetracker.models import ParsedCall


@dataclass
class FakeMarketData:
    price_usd: float


class FakeDex:
    def __init__(self, prices: list[float]) -> None:
        self.prices = prices

    async def get_current_market_data(self, _contract_address: str) -> FakeMarketData:
        return FakeMarketData(self.prices.pop(0))


def parsed_call() -> ParsedCall:
    return ParsedCall(
        ticker="TEST",
        contract_address="88npCTMN7qgCHCuCnsWcBjogn8KZ8qHAkNGmT1pWpump",
        market_cap_from_message=10000,
        token_age="5m",
        net_buy=1000,
        kol_count=7,
        discord_message_id=123,
        discord_timestamp=datetime.now(UTC) - timedelta(days=2),
        discord_author="Cielo",
    )


@pytest.mark.asyncio
async def test_result_win_threshold_uses_plus_10_percent(tmp_path) -> None:
    db = Database(str(tmp_path / "test.sqlite3"))
    await db.connect()
    parsed = parsed_call()
    alert_id = await db.insert_alert(
        parsed,
        channel_id=1,
        price_alert=1.0,
        mcap_alert=10000,
        pair_address="pair",
        dex_id="raydium",
    )
    assert alert_id is not None
    await db.set_price_15s(alert_id, 1.05)
    tracker = CieloAlertTracker(db, FakeDex([1.11]), entry_delay_seconds=0, win_threshold_percent=10)
    await tracker._check_timeframe(alert_id, parsed.discord_timestamp, "1m", 0)
    rows = await db.results_for_alert(alert_id)
    assert len(rows) == 1
    assert rows[0]["is_win_alert"] == 1
    assert rows[0]["is_win_15s"] == 0
    await db.close()


@pytest.mark.asyncio
async def test_pending_alerts_restore_unfinished_alert(tmp_path) -> None:
    db = Database(str(tmp_path / "test.sqlite3"))
    await db.connect()
    alert_id = await db.insert_alert(
        parsed_call(),
        channel_id=1,
        price_alert=1.0,
        mcap_alert=10000,
        pair_address="pair",
        dex_id="raydium",
    )
    assert alert_id is not None
    pending = await db.pending_alerts()
    assert [row["id"] for row in pending] == [alert_id]
    await db.close()
