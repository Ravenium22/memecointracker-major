from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from memetracker.database import TIMEFRAMES, Database, dt_from_str
from memetracker.market.dexscreener import DexScreenerClient
from memetracker.reporting import ReportWriter


log = logging.getLogger(__name__)


class CieloAlertTracker:
    def __init__(
        self,
        db: Database,
        dex: DexScreenerClient,
        *,
        entry_delay_seconds: int = 15,
        win_threshold_percent: float = 10.0,
        reporter: ReportWriter | None = None,
    ) -> None:
        self.db = db
        self.dex = dex
        self.entry_delay_seconds = entry_delay_seconds
        self.win_multiplier = 1 + (win_threshold_percent / 100)
        self.reporter = reporter
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    async def start(self) -> None:
        for alert in await self.db.pending_alerts():
            self.schedule_alert(int(alert["id"]), dt_from_str(alert["alert_time"]), restore=True)

    async def stop(self) -> None:
        self._closed = True
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    def schedule_alert(self, alert_id: int, alert_time: datetime, *, restore: bool = False) -> None:
        self._schedule(self._set_delayed_entry(alert_id, alert_time))
        now = datetime.now(UTC)
        for timeframe, seconds in TIMEFRAMES:
            if restore and alert_time + timedelta(seconds=seconds) < now - timedelta(seconds=30):
                continue
            self._schedule(self._check_timeframe(alert_id, alert_time, timeframe, seconds))

    def active_alert_count(self) -> int:
        return len(self._tasks)

    def _schedule(self, coro: object) -> None:
        if self._closed:
            return
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _sleep_until(self, target: datetime) -> None:
        delay = (target - datetime.now(UTC)).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)

    async def _set_delayed_entry(self, alert_id: int, alert_time: datetime) -> None:
        await self._sleep_until(alert_time + timedelta(seconds=self.entry_delay_seconds))
        alert = await self.db.get_alert(alert_id)
        if not alert or alert["price_15s"] is not None:
            return
        data = await self.dex.get_current_market_data(str(alert["token_address"]))
        if not data:
            log.warning("[DEX] no +15s price for %s", alert["token_address"])
            return
        await self.db.set_price_15s(alert_id, data.price_usd)
        if self.reporter:
            await self.reporter.maybe_write_reports()
        log.info("[TRACK] %s price_15s=%s", alert["token_name"] or alert["token_address"], data.price_usd)

    async def _check_timeframe(self, alert_id: int, alert_time: datetime, timeframe: str, seconds: int) -> None:
        await self._sleep_until(alert_time + timedelta(seconds=seconds))
        if await self.db.has_result(alert_id, timeframe):
            return
        alert = await self.db.get_alert(alert_id)
        if not alert:
            return
        data = await self.dex.get_current_market_data(str(alert["token_address"]))
        if not data:
            log.warning("[DEX] no %s price for %s", timeframe, alert["token_address"])
            return
        price_alert = float(alert["price_alert"])
        price_15s = alert["price_15s"]
        is_win_alert = data.price_usd >= price_alert * self.win_multiplier
        is_win_15s = None if price_15s is None else data.price_usd >= float(price_15s) * self.win_multiplier
        await self.db.insert_result(
            alert_id=alert_id,
            timeframe=timeframe,
            price_at_timeframe=data.price_usd,
            is_win_alert=is_win_alert,
            is_win_15s=is_win_15s,
            checked_at=datetime.now(UTC),
        )
        if self.reporter:
            await self.reporter.maybe_write_reports()
        status = "WIN" if is_win_alert else "LOSS"
        log.info("[RESULT] %s %s %s price=%s", alert["token_name"] or alert["token_address"], timeframe, status, data.price_usd)
