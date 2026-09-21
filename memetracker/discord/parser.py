from __future__ import annotations

import re
from datetime import datetime
from typing import Protocol

from memetracker.models import ParsedCall
from memetracker.utils.money import parse_money
from memetracker.utils.solana import is_plausible_solana_address


TOKEN_LINE_RE = re.compile(r"(?im)^\s*token\s*:\s*`?([A-Za-z0-9]{32,48})\b`?")
TICKER_RE = re.compile(r"#([A-Za-z0-9_]{2,20})\b")
MC_RE = re.compile(r"(?im)\bMC\s*:\s*(\$?\s*[0-9][0-9.,]*\s*[kKmMbB]?)")
NET_BUY_RE = re.compile(r"(?im)\bNet\s*Buy\s*:\s*(\$?\s*[0-9][0-9.,]*\s*[kKmMbB]?)")
AGE_RE = re.compile(r"(?im)\bAge\s*:\s*([0-9dhms\s]+)")
KOL_RE = re.compile(r"(?i)\b([0-9]+)\s+KOLs?\b")


class DiscordLikeMessage(Protocol):
    id: int
    content: str
    created_at: datetime
    author: object
    embeds: list[object]


def parse_discord_call(message: DiscordLikeMessage) -> ParsedCall | None:
    calls = parse_discord_calls(message)
    return calls[0] if calls else None


def parse_discord_calls(message: DiscordLikeMessage) -> list[ParsedCall]:
    text = combined_message_text(message)
    if not text:
        return []

    if "#solana" not in text.lower() and likely_non_solana(text):
        return []

    calls: list[ParsedCall] = []
    token_matches = list(TOKEN_LINE_RE.finditer(text))
    for index, token_match in enumerate(token_matches):
        segment = segment_for_token(text, token_match)
        parsed = parse_call_segment(message, segment, token_match.group(1), index, len(token_matches))
        if parsed:
            calls.append(parsed)
    return calls


def parse_call_segment(
    message: DiscordLikeMessage,
    text: str,
    contract_address: str,
    index: int = 0,
    total_calls: int = 1,
) -> ParsedCall | None:
    if not contract_address:
        return None
    contract_address = contract_address.strip()
    if not is_plausible_solana_address(contract_address):
        return None

    ticker = extract_ticker(text)
    mc = parse_group(MC_RE, text)
    net_buy = parse_group(NET_BUY_RE, text)
    age_match = AGE_RE.search(text)
    kol_match = KOL_RE.search(text)

    return ParsedCall(
        ticker=ticker,
        contract_address=contract_address,
        market_cap_from_message=mc,
        token_age=age_match.group(1).strip() if age_match else None,
        net_buy=net_buy,
        kol_count=int(kol_match.group(1)) if kol_match else None,
        discord_message_id=unique_message_key(int(message.id), index, total_calls),
        discord_timestamp=message.created_at,
        discord_author=str(message.author),
    )


def segment_for_token(text: str, token_match: re.Match[str]) -> str:
    start_candidates = [match.start() for match in re.finditer(r"(?im)^\s*.*?\bKOLs?\s+accumulated\b", text)]
    start = max((value for value in start_candidates if value <= token_match.start()), default=0)
    next_starts = [value for value in start_candidates if value > token_match.start()]
    end = min(next_starts) if next_starts else len(text)
    return text[start:end]


def unique_message_key(message_id: int, index: int, total_calls: int) -> int:
    if total_calls <= 1:
        return message_id
    return message_id * 1000 + index


def combined_message_text(message: DiscordLikeMessage) -> str:
    parts = [message.content or ""]
    for embed in getattr(message, "embeds", []) or []:
        for attr in ("title", "description", "url"):
            value = getattr(embed, attr, None)
            if value:
                parts.append(str(value))
        for field in getattr(embed, "fields", []) or []:
            name = getattr(field, "name", "")
            value = getattr(field, "value", "")
            parts.append(f"{name}: {value}")
    return "\n".join(parts)


def extract_ticker(text: str) -> str | None:
    for match in TICKER_RE.finditer(text):
        value = match.group(1)
        if value.lower() not in {"solana", "sol"}:
            return value.upper()
    return None


def parse_group(regex: re.Pattern[str], text: str) -> float | None:
    match = regex.search(text)
    return parse_money(match.group(1)) if match else None


def likely_non_solana(text: str) -> bool:
    lowered = text.lower()
    foreign_markers = ("#ethereum", "#eth", "#bsc", "#base", "#arbitrum", "#polygon")
    return any(marker in lowered for marker in foreign_markers)
