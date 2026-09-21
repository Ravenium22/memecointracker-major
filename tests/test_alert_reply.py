from __future__ import annotations

from datetime import UTC, datetime

from memetracker.discord.commands import alert_reply_content, alert_view, format_age


TOKEN = "88npCTMN7qgCHCuCnsWcBjogn8KZ8qHAkNGmT99pump"


def test_alert_view_has_expected_buttons() -> None:
    view = alert_view(TOKEN)
    buttons = {item.label: (item.url, item.row) for item in view.children}
    assert buttons == {
        "Trade on Terminal": (f"https://trade.padre.gg/trade/solana/{TOKEN}", 0),
        "Dexscreener": (f"https://dexscreener.com/solana/{TOKEN}", 0),
        "Defined": (f"https://www.defined.fi/token/sol/{TOKEN}", 0),
        "Sign-up on Terminal": ("https://trade.padre.gg/rk/major69", 1),
    }


def test_alert_reply_content() -> None:
    assert alert_reply_content(1_250_000, "5m") == "Mcap: $1.25m · Age: 5m"
    assert alert_reply_content(None, None) == "Mcap: n/a · Age: n/a"


def test_format_age() -> None:
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    ms = lambda seconds: int((now.timestamp() - seconds) * 1000)
    assert format_age(None) is None
    assert format_age(ms(30), now) == "1m"
    assert format_age(ms(5 * 60), now) == "5m"
    assert format_age(ms(2 * 3600 + 10 * 60), now) == "2h 10m"
    assert format_age(ms(3 * 86400), now) == "3d"
