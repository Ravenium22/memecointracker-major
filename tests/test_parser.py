from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from memetracker.discord.parser import parse_discord_call, parse_discord_calls


@dataclass
class Message:
    content: str
    id: int = 123
    created_at: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    author: str = "caller-bot"
    embeds: list = field(default_factory=list)


def test_parse_example_call() -> None:
    message = Message(
        content="""
        Moon 19 KOLs accumulated #ZEUS
        MC: $181.8k
        Age: 1h33m
        Net Buy: $15.6k
        Token: BZ9kBdCovUv5g7krWdwytNV7StLVabYTBro4DSbBpump
        #solana | Chart | X
        """
    )
    parsed = parse_discord_call(message)
    assert parsed is not None
    assert parsed.ticker == "ZEUS"
    assert parsed.contract_address == "BZ9kBdCovUv5g7krWdwytNV7StLVabYTBro4DSbBpump"
    assert parsed.market_cap_from_message == 181800
    assert parsed.token_age == "1h33m"
    assert parsed.net_buy == 15600
    assert parsed.kol_count == 19


def test_ignores_non_token_message() -> None:
    assert parse_discord_call(Message("hello #ZEUS #solana")) is None


def test_ignores_other_chain_marker() -> None:
    message = Message("MC: $1m\nToken: BZ9kBdCovUv5g7krWdwytNV7StLVabYTBro4DSbBpump\n#ethereum")
    assert parse_discord_call(message) is None


def test_parse_cielo_channel_format_without_real_links() -> None:
    message = Message(
        content="""
        9 KOLs accumulated #FairgroundAI
        MC: $37.6k
        Age: 51m
        Net Buy: $2.6k
        nyhrox: $799, cladzsol: $748, XScharo: $570, fnmilito: $334
        Token: 4T1OoeE1IvPUHmtqAxk6wNGUBSTENsjsahq1HWsPump
        #solana | Chart | X
        """
    )
    parsed = parse_discord_call(message)
    assert parsed is not None
    assert parsed.ticker == "FAIRGROUNDAI"
    assert parsed.market_cap_from_message == 37600
    assert parsed.net_buy == 2600
    assert parsed.kol_count == 9


def test_parse_cielo_markdown_token_format() -> None:
    message = Message(
        content="""
        10 KOLs accumulated #JEW
        MC: $43.5k
        Age: 5m
        Net Buy: $5.0k
        Token: `88npCTMN7qgCHCuCnsWcBjogn8KZ8qHAkNGmT1pWpump`
        #solana | [Chart](https://example.com) | [X](https://example.com)
        """
    )
    parsed = parse_discord_call(message)
    assert parsed is not None
    assert parsed.ticker == "JEW"
    assert parsed.contract_address == "88npCTMN7qgCHCuCnsWcBjogn8KZ8qHAkNGmT1pWpump"


def test_parse_multiple_calls_in_one_message() -> None:
    message = Message(
        id=999,
        content="""
        7 KOLs accumulated #CAP
        MC: $35.5k
        Age: 5m
        Net Buy: $2.1k
        Token: `4oWfioMpKcnWQXxtHHF2eSUZqEV1fk1Zi3ife4jnpump`
        #solana | Chart | X

        7 KOLs accumulated #SOCIAL
        MC: $84.6k
        Age: 6m
        Net Buy: $2.6k
        Token: `UyUfCyrC88kZKRA1Syee8amCRHYax4uoivcKs8zpump`
        #solana | Chart | X

        9 KOLs accumulated #FairgroundAI
        MC: $37.6k
        Age: 51m
        Net Buy: $2.6k
        Token: `4T1OoeE1IvPUHmtqAxk6wNGUBSTENsjsahq1HWsPump`
        #solana | Chart | X
        """,
    )
    calls = parse_discord_calls(message)
    assert [call.ticker for call in calls] == ["CAP", "SOCIAL", "FAIRGROUNDAI"]
    assert [call.discord_message_id for call in calls] == [999000, 999001, 999002]
