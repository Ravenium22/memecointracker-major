from __future__ import annotations

import asyncio
import logging

import discord

from memetracker.config import Config
from memetracker.database import Database
from memetracker.discord.commands import (
    active_embed,
    alert_reply_content,
    alert_view,
    call_embed,
    format_age,
    setup_commands,
    stats_embed,
)
from memetracker.discord.parser import parse_discord_calls
from memetracker.market.dexscreener import DexScreenerClient
from memetracker.market.tracker import CieloAlertTracker
from memetracker.reporting import ReportWriter
from memetracker.trading.executor import TradeExecutor, TradingSettings, TradeStrategySettings


log = logging.getLogger(__name__)


class MemeTrackerBot(discord.Client):
    def __init__(
        self,
        config: Config,
        db: Database,
        dex: DexScreenerClient,
        tracker: CieloAlertTracker,
        reporter: ReportWriter,
        trader: TradeExecutor,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.config = config
        self.db = db
        self.dex = dex
        self.tracker = tracker
        self.reporter = reporter
        self.trader = trader
        self.tree = discord.app_commands.CommandTree(self)
        setup_commands(self.tree, db, tracker)

    async def setup_hook(self) -> None:
        await self.tracker.start()
        await self.tree.sync()

    async def close(self) -> None:
        await self.tracker.stop()
        await self.trader.close()
        await self.dex.close()
        await self.db.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return
        if message.channel.id != self.config.discord_channel_id:
            return
        if await self._handle_text_command(message):
            return
        if self.config.cielo_author_name and self.config.cielo_author_name.lower() not in str(message.author).lower():
            return
        await self._process_alert_message(message)

    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        if payload.channel_id != self.config.discord_channel_id:
            return
        channel = self.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException as exc:
            log.warning("[DISCORD] could not fetch edited message %s for suppress: %s", payload.message_id, exc)
            return
        if message.author == self.user:
            return
        if self.config.cielo_author_name and self.config.cielo_author_name.lower() not in str(message.author).lower():
            return
        if not parse_discord_calls(message):
            return
        await self._suppress_source_embeds(message)

    async def _process_alert_message(self, message: discord.Message) -> int:
        parsed_calls = parse_discord_calls(message)
        if not parsed_calls:
            if "token:" in (message.content or "").lower():
                log.info("[PARSER] message %s contains Token: but no valid Solana alert was parsed", message.id)
            return 0

        await self._suppress_source_embeds(message)
        self._schedule_delayed_embed_suppression(message.channel.id, message.id)
        inserted = 0
        for parsed in parsed_calls:
            data = await self.dex.get_current_market_data(parsed.contract_address)
            market_cap = (data.market_cap if data else None) or parsed.market_cap_from_message
            age = parsed.token_age or format_age(data.pair_created_at if data else None)
            await self._send_alert_reply(message, parsed.contract_address, market_cap, age)
            if not data:
                log.warning("[DEX] no pair found for %s", parsed.contract_address)
                continue
            alert_id = await self.db.insert_alert(
                parsed,
                channel_id=message.channel.id,
                price_alert=data.price_usd,
                mcap_alert=data.market_cap or parsed.market_cap_from_message,
                pair_address=data.pair_address,
                dex_id=data.dex_id,
            )
            if alert_id is None:
                log.info("[ALERT] duplicate message_id=%s ignored", parsed.discord_message_id)
                continue
            self.tracker.schedule_alert(alert_id, parsed.discord_timestamp)
            await self.reporter.maybe_write_reports()
            await self.trader.on_alert(alert_id, parsed.contract_address, parsed.ticker)
            inserted += 1
            log.info("[ALERT] %s %s price=%s", parsed.ticker or "UNKNOWN", parsed.contract_address, data.price_usd)
        return inserted

    async def _suppress_source_embeds(self, message: discord.Message) -> None:
        if not message.embeds:
            return
        try:
            await message.edit(suppress=True)
            log.info("[DISCORD] suppressed embeds for message %s", message.id)
        except discord.Forbidden:
            log.warning("[DISCORD] missing permission to suppress embeds for message %s", message.id)
        except discord.HTTPException as exc:
            log.warning("[DISCORD] could not suppress embeds for message %s: %s", message.id, exc)

    def _schedule_delayed_embed_suppression(self, channel_id: int, message_id: int) -> None:
        for delay in (1, 3, 8, 20, 45, 90):
            asyncio.create_task(self._delayed_suppress_embeds(channel_id, message_id, delay))

    async def _delayed_suppress_embeds(self, channel_id: int, message_id: int, delay: int) -> None:
        await asyncio.sleep(delay)
        channel = self.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(message_id)
        except discord.HTTPException as exc:
            log.warning("[DISCORD] could not fetch message %s for delayed suppress: %s", message_id, exc)
            return
        await self._suppress_source_embeds(message)

    async def _send_alert_reply(
        self,
        message: discord.Message,
        token_address: str,
        market_cap: float | None,
        age: str | None,
    ) -> None:
        try:
            await message.reply(
                content=alert_reply_content(market_cap, age),
                view=alert_view(token_address),
                mention_author=False,
            )
        except discord.HTTPException as exc:
            log.warning("[DISCORD] could not send alert buttons for %s: %s", token_address, exc)

    async def _handle_text_command(self, message: discord.Message) -> bool:
        content = (message.content or "").strip()
        if not content.startswith("/"):
            return False
        parts = content.split()
        command = parts[0].lower()
        args = parts[1:]
        if command == "/active":
            await message.channel.send(embed=active_embed(self.tracker))
            return True
        if command == "/stats":
            period = args[0].lower() if args else "24h"
            realistic = any(arg.lower() == "realistic" for arg in args[1:])
            await message.channel.send(embed=await stats_embed(self.db, period, realistic))
            return True
        if command == "/call":
            if not args:
                await message.channel.send("Usage: `/call TICKER` or `/call TOKEN_ADDRESS`")
                return True
            await message.channel.send(embed=await call_embed(self.db, args[0]))
            return True
        if command == "/scan_recent":
            limit = 50
            if args and args[0].isdigit():
                limit = min(max(int(args[0]), 1), 200)
            inserted = 0
            async for old_message in message.channel.history(limit=limit, oldest_first=True):
                if old_message.author == self.user:
                    continue
                if self.config.cielo_author_name and self.config.cielo_author_name.lower() not in str(old_message.author).lower():
                    continue
                inserted += await self._process_alert_message(old_message)
            await message.channel.send(f"Scan complete: `{inserted}` new alert(s) imported from the last `{limit}` messages.")
            return True
        return False


async def async_main() -> None:
    config = Config.from_env()
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    db = Database(config.database_path)
    await db.connect()
    dex = DexScreenerClient(config.dexscreener_base_url)
    reporter = ReportWriter(db)
    trader = TradeExecutor(
        db,
        TradingSettings(
            enabled=config.trading_enabled,
            dry_run=config.trading_dry_run,
            rpc_url=config.solana_rpc_url,
            jupiter_base_url=config.jupiter_base_url,
            buy_amount_sol=config.buy_amount_sol,
            slippage_bps=config.slippage_bps,
            max_open_positions=config.max_open_positions,
            strategies=(
                TradeStrategySettings(
                    name="1m",
                    enabled=config.trading_1m_enabled,
                    private_key=config.wallet_private_key_1m or config.wallet_private_key,
                    sell_after_seconds=config.sell_after_seconds,
                ),
                TradeStrategySettings(
                    name="15m",
                    enabled=config.trading_15m_enabled,
                    private_key=config.wallet_private_key_15m,
                    sell_after_seconds=config.sell_after_seconds_15m,
                ),
            ),
        ),
    )
    tracker = CieloAlertTracker(
        db,
        dex,
        entry_delay_seconds=config.entry_delay_seconds,
        win_threshold_percent=config.win_threshold_percent,
        reporter=reporter,
    )
    bot = MemeTrackerBot(config, db, dex, tracker, reporter, trader)
    await bot.start(config.discord_token)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
