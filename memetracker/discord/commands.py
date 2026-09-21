from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

import discord
from discord import app_commands

from memetracker.database import TIMEFRAMES, Database
from memetracker.market.tracker import CieloAlertTracker
from memetracker.utils.money import format_money


PERIOD_CHOICES = [
    app_commands.Choice(name="24h", value="24h"),
    app_commands.Choice(name="month", value="month"),
    app_commands.Choice(name="all", value="all"),
]

MODE_CHOICES = [
    app_commands.Choice(name="theoretical", value="theoretical"),
    app_commands.Choice(name="realistic", value="realistic"),
]


def setup_commands(tree: app_commands.CommandTree, db: Database, tracker: CieloAlertTracker) -> None:
    @tree.command(name="stats", description="Show Cielo win/loss stats by timeframe.")
    @app_commands.describe(period="Stats period", mode="theoretical = T0, realistic = T+15s")
    @app_commands.choices(period=PERIOD_CHOICES, mode=MODE_CHOICES)
    async def stats(
        interaction: discord.Interaction,
        period: app_commands.Choice[str] | None = None,
        mode: app_commands.Choice[str] | None = None,
    ) -> None:
        selected_period = period.value if period else "24h"
        realistic = bool(mode and mode.value == "realistic")
        await interaction.response.send_message(embed=await stats_embed(db, selected_period, realistic))

    @tree.command(name="call", description="Show recent alerts for a token address or ticker.")
    async def call(interaction: discord.Interaction, query: str) -> None:
        await interaction.response.send_message(embed=await call_embed(db, query))

    @tree.command(name="active", description="Show how many Cielo checks are still scheduled.")
    async def active(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=active_embed(tracker))


async def stats_embed(db: Database, period: str = "24h", realistic: bool = False) -> discord.Embed:
    overview = await db.stats(period, realistic)
    mode_label = "realistic (+15s)" if realistic else "theoretical (alert)"
    embed = discord.Embed(
        title=f"Stats {period} - {mode_label}",
        color=discord.Color.blurple(),
        timestamp=datetime.now(UTC),
    )
    embed.add_field(name="Alerts", value=str(overview["total_alerts"]))
    embed.add_field(name="Unique tokens", value=str(overview["unique_tokens"]))
    table = build_stats_table(overview["rows"], realistic)
    embed.description = f"```text\n{table}\n```"
    return embed


def build_stats_table(rows: list, realistic: bool) -> str:
    buckets: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        value = row["is_win_15s"] if realistic else row["is_win_alert"]
        if value is None:
            continue
        buckets[row["timeframe"]].append(bool(value))

    lines = [
        f"{'Timeframe':<10} {'Wins':>5} {'Losses':>7} {'Winrate':>8}",
        "-" * 34,
    ]
    labels = {
        "1m": "1 min",
        "2m": "2 min",
        "5m": "5 min",
        "15m": "15 min",
        "30m": "30 min",
        "1h": "1 hour",
        "12h": "12 hours",
        "24h": "24 hours",
    }
    for timeframe, _seconds in TIMEFRAMES:
        values = buckets.get(timeframe, [])
        wins = sum(1 for value in values if value)
        losses = sum(1 for value in values if not value)
        total = wins + losses
        winrate = (wins / total * 100) if total else 0.0
        lines.append(f"{labels[timeframe]:<10} {wins:>5} {losses:>7} {winrate:>7.1f}%")
    return "\n".join(lines)


async def call_embed(db: Database, query: str) -> discord.Embed:
    alerts = await db.find_alerts(query)
    embed = discord.Embed(title=f"Alerts: {query}", color=discord.Color.blurple())
    if not alerts:
        embed.description = "No alert found."
    for alert in alerts:
        results = await db.results_for_alert(int(alert["id"]))
        lines = [
            f"Alert: `{alert['alert_time']}`",
            f"Price T0: `{alert['price_alert']:.10g}`",
            f"Price +15s: `{alert['price_15s']:.10g}`" if alert["price_15s"] is not None else "Price +15s: `pending`",
            f"MC: {format_money(alert['mcap_alert'])}",
            f"Padre: {alert['padre_url']}",
        ]
        for result in results:
            status = "WIN" if result["is_win_alert"] else "LOSS"
            realistic = "n/a" if result["is_win_15s"] is None else ("WIN" if result["is_win_15s"] else "LOSS")
            lines.append(f"`{result['timeframe']}` T0={status} +15s={realistic} price=`{result['price_at_timeframe']:.10g}`")
        embed.add_field(
            name=f"{alert['token_name'] or 'NO TICKER'} - {short_ca(alert['token_address'])}",
            value="\n".join(lines)[:1024],
            inline=False,
        )
    return embed


def active_embed(tracker: CieloAlertTracker) -> discord.Embed:
    embed = discord.Embed(title="Active checks", color=discord.Color.green())
    embed.description = f"`{tracker.active_alert_count()}` scheduled check(s)."
    return embed


def padre_view(token_address: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="Open Padre",
            style=discord.ButtonStyle.link,
            url=f"https://trade.padre.gg/trade/solana/{token_address}",
        )
    )
    return view


def short_ca(value: str) -> str:
    return f"{value[:5]}...{value[-5:]}"
