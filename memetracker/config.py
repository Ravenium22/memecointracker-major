from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    discord_token: str
    discord_channel_id: int
    dexscreener_base_url: str = "https://api.dexscreener.com"
    entry_delay_seconds: int = 15
    win_threshold_percent: float = 10.0
    database_path: str = "memetracker.sqlite3"
    log_level: str = "INFO"
    cielo_author_name: str = ""
    trading_enabled: bool = False
    trading_dry_run: bool = True
    solana_rpc_url: str = ""
    wallet_private_key: str = ""
    wallet_private_key_1m: str = ""
    wallet_private_key_15m: str = ""
    jupiter_base_url: str = "https://lite-api.jup.ag/swap/v1"
    buy_amount_sol: float = 0.02
    sell_after_seconds: int = 60
    sell_after_seconds_15m: int = 15 * 60
    trading_1m_enabled: bool = True
    trading_15m_enabled: bool = True
    slippage_bps: int = 1000
    max_open_positions: int = 3

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        token = os.getenv("DISCORD_TOKEN", "")
        channel_id = os.getenv("DISCORD_CHANNEL_ID", "")
        if not token:
            raise RuntimeError("DISCORD_TOKEN is required in .env")
        if not channel_id:
            raise RuntimeError("DISCORD_CHANNEL_ID is required in .env")

        return cls(
            discord_token=token,
            discord_channel_id=int(channel_id),
            dexscreener_base_url=os.getenv("DEXSCREENER_BASE_URL", "https://api.dexscreener.com").rstrip("/"),
            entry_delay_seconds=int(os.getenv("ENTRY_DELAY_SECONDS", "15")),
            win_threshold_percent=float(os.getenv("WIN_THRESHOLD_PERCENT", "10")),
            database_path=os.getenv("DATABASE_PATH", str(Path("memetracker.sqlite3"))),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            cielo_author_name=os.getenv("CIELO_AUTHOR_NAME", "").strip(),
            trading_enabled=parse_bool(os.getenv("TRADING_ENABLED", "false")),
            trading_dry_run=parse_bool(os.getenv("TRADING_DRY_RUN", "true")),
            solana_rpc_url=os.getenv("SOLANA_RPC_URL", "").strip(),
            wallet_private_key=os.getenv("WALLET_PRIVATE_KEY", "").strip(),
            wallet_private_key_1m=os.getenv("WALLET_PRIVATE_KEY_1M", os.getenv("WALLET_PRIVATE_KEY", "")).strip(),
            wallet_private_key_15m=os.getenv("WALLET_PRIVATE_KEY_15M", "").strip(),
            jupiter_base_url=os.getenv("JUPITER_BASE_URL", "https://lite-api.jup.ag/swap/v1").rstrip("/"),
            buy_amount_sol=float(os.getenv("BUY_AMOUNT_SOL", "0.02")),
            sell_after_seconds=int(os.getenv("SELL_AFTER_SECONDS", "60")),
            sell_after_seconds_15m=int(os.getenv("SELL_AFTER_SECONDS_15M", str(15 * 60))),
            trading_1m_enabled=parse_bool(os.getenv("TRADING_1M_ENABLED", "true")),
            trading_15m_enabled=parse_bool(os.getenv("TRADING_15M_ENABLED", "true")),
            slippage_bps=int(os.getenv("SLIPPAGE_BPS", "1000")),
            max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "3")),
        )


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
