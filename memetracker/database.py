from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from memetracker.models import ParsedCall


TIMEFRAMES: tuple[tuple[str, int], ...] = (
    ("1m", 1 * 60),
    ("2m", 2 * 60),
    ("5m", 5 * 60),
    ("15m", 15 * 60),
    ("30m", 30 * 60),
    ("1h", 60 * 60),
    ("12h", 12 * 60 * 60),
    ("24h", 24 * 60 * 60),
)


def dt_to_str(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def dt_from_str(value: str) -> datetime:
    return datetime.fromisoformat(value)


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.init_schema()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    def _db(self) -> aiosqlite.Connection:
        if self.conn is None:
            raise RuntimeError("Database is not connected")
        return self.conn

    async def init_schema(self) -> None:
        await self._db().executescript(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_address TEXT NOT NULL,
                token_name TEXT,
                alert_time TEXT NOT NULL,
                price_alert REAL NOT NULL,
                price_15s REAL,
                mcap_alert REAL,
                message_id TEXT NOT NULL UNIQUE,
                channel_id TEXT NOT NULL,
                pair_address TEXT,
                dex_id TEXT,
                padre_url TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER NOT NULL,
                timeframe TEXT NOT NULL,
                price_at_timeframe REAL NOT NULL,
                is_win_alert INTEGER NOT NULL,
                is_win_15s INTEGER,
                checked_at TEXT NOT NULL,
                UNIQUE(alert_id, timeframe),
                FOREIGN KEY(alert_id) REFERENCES alerts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS real_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER NOT NULL,
                token_address TEXT NOT NULL,
                token_name TEXT,
                strategy_name TEXT NOT NULL DEFAULT '1m',
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                buy_amount_lamports INTEGER NOT NULL,
                sell_after_seconds INTEGER NOT NULL DEFAULT 60,
                quoted_token_amount_raw INTEGER,
                buy_signature TEXT,
                sell_signature TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                buy_submitted_at TEXT,
                sell_submitted_at TEXT,
                FOREIGN KEY(alert_id) REFERENCES alerts(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_alerts_token_address ON alerts(token_address);
            CREATE INDEX IF NOT EXISTS idx_alerts_alert_time ON alerts(alert_time);
            CREATE INDEX IF NOT EXISTS idx_alerts_message_id ON alerts(message_id);
            CREATE INDEX IF NOT EXISTS idx_results_alert_timeframe ON results(alert_id, timeframe);
            CREATE INDEX IF NOT EXISTS idx_results_timeframe ON results(timeframe);
            CREATE INDEX IF NOT EXISTS idx_real_trades_alert_id ON real_trades(alert_id);
            CREATE INDEX IF NOT EXISTS idx_real_trades_status ON real_trades(status);
            """
        )
        await self._ensure_real_trade_columns()
        await self._db().execute("CREATE INDEX IF NOT EXISTS idx_real_trades_strategy ON real_trades(strategy_name)")
        await self._db().commit()

    async def insert_alert(
        self,
        parsed: ParsedCall,
        *,
        channel_id: int,
        price_alert: float,
        mcap_alert: float | None,
        pair_address: str | None,
        dex_id: str | None,
    ) -> int | None:
        padre_url = f"https://trade.padre.gg/trade/solana/{parsed.contract_address}"
        try:
            cursor = await self._db().execute(
                """
                INSERT INTO alerts (
                    token_address, token_name, alert_time, price_alert, price_15s,
                    mcap_alert, message_id, channel_id, pair_address, dex_id, padre_url, created_at
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    parsed.contract_address,
                    parsed.ticker,
                    dt_to_str(parsed.discord_timestamp),
                    price_alert,
                    mcap_alert,
                    str(parsed.discord_message_id),
                    str(channel_id),
                    pair_address,
                    dex_id,
                    padre_url,
                    dt_to_str(datetime.now(UTC)),
                ),
            )
            await self._db().commit()
            return int(cursor.lastrowid)
        except aiosqlite.IntegrityError:
            return None

    async def set_price_15s(self, alert_id: int, price_15s: float) -> None:
        await self._db().execute("UPDATE alerts SET price_15s = ? WHERE id = ?", (price_15s, alert_id))
        await self._db().commit()

    async def insert_result(
        self,
        *,
        alert_id: int,
        timeframe: str,
        price_at_timeframe: float,
        is_win_alert: bool,
        is_win_15s: bool | None,
        checked_at: datetime,
    ) -> None:
        await self._db().execute(
            """
            INSERT OR IGNORE INTO results (
                alert_id, timeframe, price_at_timeframe, is_win_alert, is_win_15s, checked_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                timeframe,
                price_at_timeframe,
                int(is_win_alert),
                None if is_win_15s is None else int(is_win_15s),
                dt_to_str(checked_at),
            ),
        )
        await self._db().commit()

    async def get_alert(self, alert_id: int) -> aiosqlite.Row | None:
        return await fetch_one(self._db(), "SELECT * FROM alerts WHERE id = ?", (alert_id,))

    async def pending_alerts(self) -> list[aiosqlite.Row]:
        rows = await self._db().execute_fetchall(
            """
            SELECT * FROM alerts
            WHERE (
                price_15s IS NULL
                OR (
                    SELECT COUNT(*) FROM results WHERE results.alert_id = alerts.id
                ) < ?
            )
            ORDER BY alert_time ASC
            """,
            (len(TIMEFRAMES),),
        )
        return rows

    async def has_result(self, alert_id: int, timeframe: str) -> bool:
        row = await fetch_one(
            self._db(),
            "SELECT 1 FROM results WHERE alert_id = ? AND timeframe = ?",
            (alert_id, timeframe),
        )
        return row is not None

    async def stats(self, period: str, realistic: bool = False) -> dict[str, Any]:
        since = period_start(period)
        where = ""
        params: tuple[Any, ...] = ()
        if since is not None:
            where = "WHERE a.alert_time >= ?"
            params = (dt_to_str(since),)
        rows = await self._db().execute_fetchall(
            f"""
            SELECT r.timeframe, r.is_win_alert, r.is_win_15s
            FROM results r
            JOIN alerts a ON a.id = r.alert_id
            {where}
            ORDER BY r.timeframe
            """,
            params,
        )
        total_alerts_row = await fetch_one(self._db(), f"SELECT COUNT(*) n FROM alerts a {where}", params)
        unique_tokens_row = await fetch_one(
            self._db(),
            f"SELECT COUNT(DISTINCT token_address) n FROM alerts a {where}",
            params,
        )
        return {
            "period": period,
            "realistic": realistic,
            "total_alerts": total_alerts_row["n"] if total_alerts_row else 0,
            "unique_tokens": unique_tokens_row["n"] if unique_tokens_row else 0,
            "rows": rows,
        }

    async def find_alerts(self, query: str, limit: int = 5) -> list[aiosqlite.Row]:
        like = f"%{query.upper()}%"
        return await self._db().execute_fetchall(
            """
            SELECT * FROM alerts
            WHERE UPPER(COALESCE(token_name, '')) LIKE ? OR token_address = ?
            ORDER BY alert_time DESC
            LIMIT ?
            """,
            (like, query, limit),
        )

    async def results_for_alert(self, alert_id: int) -> list[aiosqlite.Row]:
        return await self._db().execute_fetchall(
            "SELECT * FROM results WHERE alert_id = ? ORDER BY checked_at",
            (alert_id,),
        )

    async def alert_count(self) -> int:
        row = await fetch_one(self._db(), "SELECT COUNT(*) n FROM alerts")
        return int(row["n"]) if row else 0

    async def report_rows(self, checkpoint: int) -> list[aiosqlite.Row]:
        return await self._db().execute_fetchall(
            """
            WITH selected_alerts AS (
                SELECT id, price_alert, price_15s
                FROM alerts
                ORDER BY id ASC
                LIMIT ?
            )
            SELECT
                r.timeframe,
                r.price_at_timeframe,
                r.is_win_alert,
                r.is_win_15s,
                a.price_alert,
                a.price_15s
            FROM results r
            JOIN selected_alerts a ON a.id = r.alert_id
            ORDER BY r.timeframe, r.checked_at
            """,
            (checkpoint,),
        )

    async def create_trade(
        self,
        *,
        alert_id: int,
        token_address: str,
        token_name: str | None,
        strategy_name: str,
        mode: str,
        status: str,
        buy_amount_lamports: int,
        sell_after_seconds: int,
        quoted_token_amount_raw: int | None = None,
        buy_signature: str | None = None,
    ) -> int:
        cursor = await self._db().execute(
            """
            INSERT INTO real_trades (
                alert_id, token_address, token_name, strategy_name, mode, status,
                buy_amount_lamports, sell_after_seconds, quoted_token_amount_raw,
                buy_signature, created_at, buy_submitted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                token_address,
                token_name,
                strategy_name,
                mode,
                status,
                buy_amount_lamports,
                sell_after_seconds,
                quoted_token_amount_raw,
                buy_signature,
                dt_to_str(datetime.now(UTC)),
                dt_to_str(datetime.now(UTC)) if buy_signature else None,
            ),
        )
        await self._db().commit()
        return int(cursor.lastrowid)

    async def update_trade_sell(
        self,
        trade_id: int,
        *,
        status: str,
        sell_signature: str | None = None,
        error: str | None = None,
    ) -> None:
        await self._db().execute(
            """
            UPDATE real_trades
            SET status = ?, sell_signature = ?, error = ?, sell_submitted_at = ?
            WHERE id = ?
            """,
            (
                status,
                sell_signature,
                error,
                dt_to_str(datetime.now(UTC)) if sell_signature else None,
                trade_id,
            ),
        )
        await self._db().commit()

    async def mark_trade_error(self, trade_id: int, status: str, error: str) -> None:
        await self._db().execute(
            "UPDATE real_trades SET status = ?, error = ? WHERE id = ?",
            (status, error, trade_id),
        )
        await self._db().commit()

    async def open_trade_count(self) -> int:
        row = await fetch_one(
            self._db(),
            "SELECT COUNT(*) n FROM real_trades WHERE status IN ('OPEN', 'DRY_RUN_OPEN')",
        )
        return int(row["n"]) if row else 0

    async def _ensure_real_trade_columns(self) -> None:
        columns = {
            row["name"]
            for row in await self._db().execute_fetchall("PRAGMA table_info(real_trades)")
        }
        if "strategy_name" not in columns:
            await self._db().execute("ALTER TABLE real_trades ADD COLUMN strategy_name TEXT NOT NULL DEFAULT '1m'")
        if "sell_after_seconds" not in columns:
            await self._db().execute("ALTER TABLE real_trades ADD COLUMN sell_after_seconds INTEGER NOT NULL DEFAULT 60")


async def fetch_one(db: aiosqlite.Connection, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
    cursor = await db.execute(sql, params)
    row = await cursor.fetchone()
    await cursor.close()
    return row


def period_start(period: str) -> datetime | None:
    now = datetime.now(UTC)
    normalized = period.lower()
    if normalized in {"24h", "day"}:
        return now - timedelta(hours=24)
    if normalized in {"month", "30d"}:
        return now - timedelta(days=30)
    if normalized == "all":
        return None
    return now - timedelta(hours=24)


def timeframe_seconds(timeframe: str) -> int:
    for name, seconds in TIMEFRAMES:
        if name == timeframe:
            return seconds
    raise ValueError(f"Unknown timeframe: {timeframe}")
