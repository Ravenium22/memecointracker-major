from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from solders.keypair import Keypair

from memetracker.database import Database
from memetracker.trading.jupiter import LAMPORTS_PER_SOL, WSOL_MINT, JupiterClient
from memetracker.trading.wallet import load_keypair


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TradeStrategySettings:
    name: str
    enabled: bool
    private_key: str
    sell_after_seconds: int


@dataclass(frozen=True)
class TradingSettings:
    enabled: bool
    dry_run: bool
    rpc_url: str
    jupiter_base_url: str
    buy_amount_sol: float
    slippage_bps: int
    max_open_positions: int
    strategies: tuple[TradeStrategySettings, ...]

    @property
    def buy_amount_lamports(self) -> int:
        return int(self.buy_amount_sol * LAMPORTS_PER_SOL)


class TradeExecutor:
    def __init__(self, db: Database, settings: TradingSettings) -> None:
        self.db = db
        self.settings = settings
        self.jupiter = JupiterClient(settings.jupiter_base_url, settings.rpc_url)
        self.keypairs: dict[str, Keypair] = {}
        if settings.enabled and not settings.dry_run:
            for strategy in settings.strategies:
                if strategy.enabled:
                    self.keypairs[strategy.name] = load_keypair(strategy.private_key)

    async def close(self) -> None:
        await self.jupiter.close()

    async def on_alert(self, alert_id: int, token_address: str, token_name: str | None) -> None:
        if not self.settings.enabled:
            return
        for strategy in self.settings.strategies:
            if not strategy.enabled:
                continue
            open_count = await self.db.open_trade_count()
            if open_count >= self.settings.max_open_positions:
                log.warning("[TRADE] max open positions reached; skipping %s %s", strategy.name, token_address)
                continue
            asyncio.create_task(self._buy_then_sell(strategy, alert_id, token_address, token_name))

    async def _buy_then_sell(
        self,
        strategy: TradeStrategySettings,
        alert_id: int,
        token_address: str,
        token_name: str | None,
    ) -> None:
        trade_id: int | None = None
        try:
            buy_quote = await self.jupiter.quote(
                WSOL_MINT,
                token_address,
                self.settings.buy_amount_lamports,
                self.settings.slippage_bps,
            )
            quoted_amount = int(buy_quote.get("outAmount", "0"))
            mode = "DRY_RUN" if self.settings.dry_run else "LIVE"
            if self.settings.dry_run:
                trade_id = await self.db.create_trade(
                    alert_id=alert_id,
                    token_address=token_address,
                    token_name=token_name,
                    strategy_name=strategy.name,
                    mode=mode,
                    status="DRY_RUN_OPEN",
                    buy_amount_lamports=self.settings.buy_amount_lamports,
                    sell_after_seconds=strategy.sell_after_seconds,
                    quoted_token_amount_raw=quoted_amount,
                )
                log.info(
                    "[TRADE] DRY RUN %s buy %s amount_sol=%s quoted_raw=%s",
                    strategy.name,
                    token_name or token_address,
                    self.settings.buy_amount_sol,
                    quoted_amount,
                )
            else:
                keypair = self.keypairs[strategy.name]
                signature = await self.jupiter.sign_and_send_swap(buy_quote, keypair)
                trade_id = await self.db.create_trade(
                    alert_id=alert_id,
                    token_address=token_address,
                    token_name=token_name,
                    strategy_name=strategy.name,
                    mode=mode,
                    status="OPEN",
                    buy_amount_lamports=self.settings.buy_amount_lamports,
                    sell_after_seconds=strategy.sell_after_seconds,
                    quoted_token_amount_raw=quoted_amount,
                    buy_signature=signature,
                )
                log.info("[TRADE] LIVE %s buy %s signature=%s", strategy.name, token_name or token_address, signature)

            await asyncio.sleep(strategy.sell_after_seconds)
            await self._sell(strategy, trade_id, token_address, quoted_amount)
        except Exception as exc:
            log.exception("[TRADE] %s failed for %s", strategy.name, token_address)
            if trade_id is not None:
                await self.db.mark_trade_error(trade_id, "ERROR", str(exc))

    async def _sell(
        self,
        strategy: TradeStrategySettings,
        trade_id: int,
        token_address: str,
        fallback_amount_raw: int,
    ) -> None:
        try:
            amount_raw = fallback_amount_raw
            if not self.settings.dry_run:
                keypair = self.keypairs[strategy.name]
                amount_raw = await self.jupiter.token_balance_raw(str(keypair.pubkey()), token_address)
            if amount_raw <= 0:
                await self.db.update_trade_sell(trade_id, status="SELL_SKIPPED", error="No token balance/quote amount to sell")
                return
            sell_quote = await self.jupiter.quote(token_address, WSOL_MINT, amount_raw, self.settings.slippage_bps)
            if self.settings.dry_run:
                await self.db.update_trade_sell(trade_id, status="DRY_RUN_CLOSED")
                log.info("[TRADE] DRY RUN %s sell token=%s raw=%s", strategy.name, token_address, amount_raw)
            else:
                keypair = self.keypairs[strategy.name]
                signature = await self.jupiter.sign_and_send_swap(sell_quote, keypair)
                await self.db.update_trade_sell(trade_id, status="CLOSED", sell_signature=signature)
                log.info("[TRADE] LIVE %s sell token=%s signature=%s", strategy.name, token_address, signature)
        except Exception as exc:
            log.exception("[TRADE] %s sell failed for %s", strategy.name, token_address)
            await self.db.update_trade_sell(trade_id, status="SELL_ERROR", error=str(exc))

