from __future__ import annotations

from datetime import UTC, datetime

import pytest

from memetracker.database import Database
from memetracker.models import ParsedCall
from memetracker.reporting import ReportWriter


def parsed_call(index: int) -> ParsedCall:
    return ParsedCall(
        ticker=f"T{index}",
        contract_address=f"88npCTMN7qgCHCuCnsWcBjogn8KZ8qHAkNGmT{index:02d}pump",
        market_cap_from_message=10000,
        token_age="5m",
        net_buy=1000,
        kol_count=7,
        discord_message_id=1000 + index,
        discord_timestamp=datetime.now(UTC),
        discord_author="Cielo",
    )


@pytest.mark.asyncio
async def test_report_writer_creates_25_call_report(tmp_path) -> None:
    db = Database(str(tmp_path / "test.sqlite3"))
    await db.connect()
    for index in range(25):
        alert_id = await db.insert_alert(
            parsed_call(index),
            channel_id=1,
            price_alert=1.0,
            mcap_alert=10000,
            pair_address="pair",
            dex_id="raydium",
        )
        assert alert_id is not None
    await db.insert_result(
        alert_id=1,
        timeframe="1m",
        price_at_timeframe=1.2,
        is_win_alert=True,
        is_win_15s=None,
        checked_at=datetime.now(UTC),
    )
    reporter = ReportWriter(db, reports_dir=str(tmp_path / "reports"))
    await reporter.maybe_write_reports()
    report = tmp_path / "reports" / "report_025_calls.txt"
    latest = tmp_path / "reports" / "latest_report.txt"
    assert report.exists()
    assert latest.exists()
    text = report.read_text(encoding="utf-8")
    assert "first 25 calls" in text
    assert "1m" in text
    assert "20s" not in text
    await db.close()
