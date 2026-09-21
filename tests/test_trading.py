from __future__ import annotations

from datetime import UTC, datetime

import pytest

from memetracker.database import Database
from memetracker.models import ParsedCall
from memetracker.trading.executor import TradeExecutor, TradingSettings, TradeStrategySettings


class FakeJupiter:
    async def close(self) -> None:
        pass

    async def quote(self, input_mint: str, output_mint: str, amount: int, slippage_bps: int) -> dict:
        return {"outAmount": "12345", "inputMint": input_mint, "outputMint": output_mint, "amount": str(amount)}


def parsed_call() -> ParsedCall:
    return ParsedCall(
        ticker="TEST",
        contract_address="88npCTMN7qgCHCuCnsWcBjogn8KZ8qHAkNGmT99pump",
        market_cap_from_message=10000,
        token_age="5m",
        net_buy=1000,
        kol_count=7,
        discord_message_id=999,
        discord_timestamp=datetime.now(UTC),
        discord_author="Cielo",
    )


@pytest.mark.asyncio
async def test_trade_executor_dry_run_buy_and_sell_for_two_strategies(tmp_path) -> None:
    db = Database(str(tmp_path / "test.sqlite3"))
    await db.connect()
    parsed = parsed_call()
    alert_id = await db.insert_alert(
        parsed,
        channel_id=1,
        price_alert=1.0,
        mcap_alert=10000,
        pair_address="pair",
        dex_id="pumpswap",
    )
    assert alert_id is not None
    one_min = TradeStrategySettings(name="1m", enabled=True, private_key="", sell_after_seconds=0)
    fifteen_min = TradeStrategySettings(name="15m", enabled=True, private_key="", sell_after_seconds=0)
    executor = TradeExecutor(
        db,
        TradingSettings(
            enabled=True,
            dry_run=True,
            rpc_url="",
            jupiter_base_url="https://example.com",
            buy_amount_sol=0.02,
            slippage_bps=1000,
            max_open_positions=3,
            strategies=(one_min, fifteen_min),
        ),
    )
    executor.jupiter = FakeJupiter()
    await executor._buy_then_sell(one_min, alert_id, parsed.contract_address, parsed.ticker)
    await executor._buy_then_sell(fifteen_min, alert_id, parsed.contract_address, parsed.ticker)
    rows = await db._db().execute_fetchall("SELECT * FROM real_trades")
    assert len(rows) == 2
    assert {row["strategy_name"] for row in rows} == {"1m", "15m"}
    assert {row["mode"] for row in rows} == {"DRY_RUN"}
    assert {row["status"] for row in rows} == {"DRY_RUN_CLOSED"}
    assert {row["buy_amount_lamports"] for row in rows} == {20_000_000}
    await db.close()
