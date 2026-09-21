from __future__ import annotations

import re


PLAUSIBLE_SOLANA_RE = re.compile(r"^[A-Za-z0-9]{32,48}$")


def is_plausible_solana_address(value: str | None) -> bool:
    if not value:
        return False
    return bool(PLAUSIBLE_SOLANA_RE.fullmatch(value.strip()))
