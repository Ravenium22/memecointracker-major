from __future__ import annotations

import re


MONEY_RE = re.compile(r"\$?\s*([0-9]+(?:[.,][0-9]+)?)\s*([kKmMbB])?")


def parse_money(value: str | None) -> float | None:
    if not value:
        return None
    match = MONEY_RE.search(value.replace("\u00a0", " "))
    if not match:
        return None
    number = float(match.group(1).replace(",", "."))
    suffix = (match.group(2) or "").lower()
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[suffix]
    return number * multiplier


def format_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}b"
    if abs_value >= 1_000_000:
        return f"${value / 1_000_000:.2f}m"
    if abs_value >= 1_000:
        return f"${value / 1_000:.2f}k"
    return f"${value:.6g}"

