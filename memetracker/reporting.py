from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from memetracker.database import TIMEFRAMES, Database


class ReportWriter:
    def __init__(self, db: Database, reports_dir: str = "reports", step: int = 25) -> None:
        self.db = db
        self.reports_dir = Path(reports_dir)
        self.step = step
        self._lock = asyncio.Lock()

    async def maybe_write_reports(self) -> None:
        async with self._lock:
            total = await self.db.alert_count()
            if total < self.step:
                return
            checkpoints = range(self.step, (total // self.step) * self.step + 1, self.step)
            latest_text = ""
            for checkpoint in checkpoints:
                text = await self.build_report(checkpoint)
                latest_text = text
                await asyncio.to_thread(self._write_report_file, checkpoint, text)
            if latest_text:
                await asyncio.to_thread((self.reports_dir / "latest_report.txt").write_text, latest_text, "utf-8")

    async def build_report(self, checkpoint: int) -> str:
        rows = await self.db.report_rows(checkpoint)
        now = datetime.now(UTC).isoformat(timespec="seconds")
        lines = [
            f"Cielo Alert Tracker report - first {checkpoint} calls",
            f"Generated at: {now}",
            "",
            "Theoretical entry: T0 alert price",
            self._summary_table(rows, realistic=False),
            "",
            "Realistic entry: T+15s price",
            self._summary_table(rows, realistic=True),
            "",
            "Note: each timeframe uses completed checks only. A +7% move is still a LOSS if the win threshold is +10%, but ROI remains +7%.",
        ]
        return "\n".join(lines) + "\n"

    def _summary_table(self, rows: list, *, realistic: bool) -> str:
        buckets: dict[str, list[tuple[bool, float]]] = defaultdict(list)
        for row in rows:
            reference = row["price_15s"] if realistic else row["price_alert"]
            is_win = row["is_win_15s"] if realistic else row["is_win_alert"]
            if reference is None or is_win is None:
                continue
            roi = ((float(row["price_at_timeframe"]) / float(reference)) - 1) * 100
            buckets[row["timeframe"]].append((bool(is_win), roi))

        lines = [
            f"{'Timeframe':<9} {'Trades':>6} {'Wins':>5} {'Losses':>7} {'Winrate':>8} {'Avg ROI':>9} {'Avg Win':>9} {'Avg Loss':>9}",
            "-" * 78,
        ]
        for timeframe, _seconds in TIMEFRAMES:
            values = buckets.get(timeframe, [])
            wins = [roi for is_win, roi in values if is_win]
            losses = [roi for is_win, roi in values if not is_win]
            all_rois = [roi for _is_win, roi in values]
            total = len(values)
            winrate = (len(wins) / total * 100) if total else 0.0
            lines.append(
                f"{timeframe:<9} {total:>6} {len(wins):>5} {len(losses):>7} "
                f"{winrate:>7.1f}% {avg(all_rois):>8.2f}% {avg(wins):>8.2f}% {avg(losses):>8.2f}%"
            )
        return "\n".join(lines)

    def _write_report_file(self, checkpoint: int, text: str) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        path = self.reports_dir / f"report_{checkpoint:03d}_calls.txt"
        path.write_text(text, encoding="utf-8")


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0

