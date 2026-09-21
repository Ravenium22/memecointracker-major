from __future__ import annotations

import json

from solders.keypair import Keypair


def load_keypair(raw_private_key: str) -> Keypair:
    value = raw_private_key.strip()
    if not value:
        raise ValueError("WALLET_PRIVATE_KEY is required for live trading")
    if value.startswith("["):
        data = json.loads(value)
        if not isinstance(data, list):
            raise ValueError("WALLET_PRIVATE_KEY JSON must be an array of integers")
        return Keypair.from_bytes(bytes(data))
    return Keypair.from_base58_string(value)

