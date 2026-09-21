from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp
from solders.keypair import Keypair
from solders.message import to_bytes_versioned
from solders.transaction import VersionedTransaction


log = logging.getLogger(__name__)

WSOL_MINT = "So11111111111111111111111111111111111111112"
LAMPORTS_PER_SOL = 1_000_000_000


@dataclass(slots=True)
class SwapResult:
    signature: str | None
    out_amount: int
    quote: dict[str, Any]


class JupiterClient:
    def __init__(self, base_url: str, rpc_url: str, timeout_seconds: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.rpc_url = rpc_url.strip()
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=self.timeout)

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def quote(self, input_mint: str, output_mint: str, amount: int, slippage_bps: int) -> dict[str, Any]:
        await self.start()
        assert self.session is not None
        async with self.session.get(
            f"{self.base_url}/quote",
            params={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount),
                "slippageBps": str(slippage_bps),
                "swapMode": "ExactIn",
            },
        ) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"Jupiter quote failed HTTP {response.status}: {text[:300]}")
            return await response.json()

    async def swap_transaction(self, quote: dict[str, Any], user_public_key: str) -> str:
        await self.start()
        assert self.session is not None
        payload = {
            "quoteResponse": quote,
            "userPublicKey": user_public_key,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto",
        }
        async with self.session.post(f"{self.base_url}/swap", json=payload) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"Jupiter swap failed HTTP {response.status}: {text[:300]}")
            data = await response.json()
        swap_tx = data.get("swapTransaction")
        if not swap_tx:
            raise RuntimeError("Jupiter swap response did not include swapTransaction")
        return str(swap_tx)

    async def sign_and_send_swap(self, quote: dict[str, Any], keypair: Keypair) -> str:
        swap_tx = await self.swap_transaction(quote, str(keypair.pubkey()))
        raw_tx = base64.b64decode(swap_tx)
        tx = VersionedTransaction.from_bytes(raw_tx)
        signature = keypair.sign_message(to_bytes_versioned(tx.message))
        signed_tx = VersionedTransaction.populate(tx.message, [signature])
        encoded = base64.b64encode(bytes(signed_tx)).decode("ascii")
        return await self.send_raw_transaction(encoded)

    async def send_raw_transaction(self, encoded_transaction: str) -> str:
        if not self.rpc_url:
            raise RuntimeError("SOLANA_RPC_URL is required for live trading")
        await self.start()
        assert self.session is not None
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                encoded_transaction,
                {"encoding": "base64", "skipPreflight": False, "maxRetries": 3},
            ],
        }
        async with self.session.post(self.rpc_url, json=payload) as response:
            data = await response.json()
        if "error" in data:
            raise RuntimeError(f"Solana RPC sendTransaction failed: {data['error']}")
        return str(data["result"])

    async def token_balance_raw(self, owner: str, mint: str) -> int:
        if not self.rpc_url:
            raise RuntimeError("SOLANA_RPC_URL is required to read token balances")
        await self.start()
        assert self.session is not None
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                owner,
                {"mint": mint},
                {"encoding": "jsonParsed"},
            ],
        }
        async with self.session.post(self.rpc_url, json=payload) as response:
            data = await response.json()
        if "error" in data:
            raise RuntimeError(f"Solana RPC getTokenAccountsByOwner failed: {data['error']}")
        total = 0
        for item in data.get("result", {}).get("value", []):
            info = item.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            amount = info.get("tokenAmount", {}).get("amount")
            if amount is not None:
                total += int(amount)
        return total

