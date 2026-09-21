# Cielo Alert Tracker

Local Discord bot that listens to a Cielo alert channel, records the Solana token price at alert time, then checks performance across fixed timeframes.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configuration

Create/fill `.env`:

```env
DISCORD_TOKEN=
DISCORD_CHANNEL_ID=
DEXSCREENER_BASE_URL=https://api.dexscreener.com
ENTRY_DELAY_SECONDS=15
WIN_THRESHOLD_PERCENT=10
DATABASE_PATH=memetracker.sqlite3
LOG_LEVEL=INFO
CIELO_AUTHOR_NAME=
TRADING_ENABLED=false
TRADING_DRY_RUN=true
SOLANA_RPC_URL=
WALLET_PRIVATE_KEY=
WALLET_PRIVATE_KEY_1M=
WALLET_PRIVATE_KEY_15M=
JUPITER_BASE_URL=https://lite-api.jup.ag/swap/v1
BUY_AMOUNT_SOL=0.02
SELL_AFTER_SECONDS=60
SELL_AFTER_SECONDS_15M=900
TRADING_1M_ENABLED=true
TRADING_15M_ENABLED=true
SLIPPAGE_BPS=1000
MAX_OPEN_POSITIONS=3
```

`CIELO_AUTHOR_NAME` is optional. If set to `Cielo`, the bot ignores messages from authors whose name does not contain `Cielo`.

## Logic

For each alert:

- T0 price: fetched immediately through DexScreener
- +15s price: fetched after `ENTRY_DELAY_SECONDS`
- checks: `20s`, `1m`, `2m`, `5m`, `15m`, `30m`, `1h`, `12h`, `24h`
- win: timeframe price >= reference price + `WIN_THRESHOLD_PERCENT`
- loss: timeframe price < reference price + `WIN_THRESHOLD_PERCENT`

SQLite tables:

- `alerts`
- `results`

## Commands

```text
/stats 24h
/stats month
/stats all
/stats 24h realistic
/call TOKEN_OR_TICKER
/active
/scan_recent 50
```

`realistic` uses the +15s entry. Without `realistic`, stats use the T0 alert price.

## Local Reports

The bot writes text reports every 25 calls:

```text
reports/report_025_calls.txt
reports/report_050_calls.txt
reports/report_075_calls.txt
reports/latest_report.txt
```

Reports are updated again as delayed timeframe checks complete. They include every active timeframe with trades, wins, losses, winrate, average ROI, average win ROI, and average loss ROI.

## Local Start

```powershell
python -m memetracker.bot
```

Useful Discord permissions:

- View Channel
- Read Message History
- Send Messages
- Use Slash Commands
- Message Content Intent
- Manage Messages, only if you want the bot to suppress Cielo embeds

The bot replies to new alerts with a Padre button:

```text
https://trade.padre.gg/trade/solana/{TOKEN_ADDRESS}
```

## Real Trading

Real trading is disabled by default.

The live trading strategies are:

- `1m`: buy immediately when a valid Cielo call is detected, sell after `SELL_AFTER_SECONDS`, currently `60`
- `15m`: buy immediately when a valid Cielo call is detected, sell after `SELL_AFTER_SECONDS_15M`, currently `900`
- both use `BUY_AMOUNT_SOL`, currently `0.02`
- swaps are routed through Jupiter

Keep this default while testing:

```env
TRADING_ENABLED=false
TRADING_DRY_RUN=true
```

Dry-run mode fetches Jupiter quotes and records simulated trades, but does not sign or send transactions.

For live trading, use a dedicated wallet only, never your main wallet. Fill:

```env
SOLANA_RPC_URL=https://solana-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY
WALLET_PRIVATE_KEY=
WALLET_PRIVATE_KEY_1M=
WALLET_PRIVATE_KEY_15M=
```

`WALLET_PRIVATE_KEY_1M` is the dedicated wallet for the 1-minute strategy.

`WALLET_PRIVATE_KEY_15M` is the dedicated wallet for the 15-minute strategy.

`WALLET_PRIVATE_KEY` is kept as a fallback for the 1-minute strategy.

Each private key can be either:

- a base58 Solana private key string
- a JSON array exported from a Solana keypair file

Then enable live trading explicitly:

```env
TRADING_ENABLED=true
TRADING_DRY_RUN=false
```

Do not share `.env`. Anyone with the private key can drain the wallet.

## Railway Deployment

The repo includes a `Procfile`, `railway.json`, and `.python-version` so Railway can build and start the bot with no extra setup.

1. Create a new Railway project from this GitHub repo.
2. In the service **Variables** tab, add every key from `.env.example`. At minimum:
   - `DISCORD_TOKEN`
   - `DISCORD_CHANNEL_ID`
   - `TRADING_ENABLED=false`
   - `TRADING_DRY_RUN=true`
3. Attach a **Volume** to the service (for example mounted at `/data`) and set `DATABASE_PATH=/data/memetracker.sqlite3`. Without a volume the SQLite database is wiped on every redeploy.
4. Deploy. The bot has no HTTP server, so Railway will not generate a public domain. That is expected.

Never commit `.env`. It is gitignored. Wallet private keys belong only in Railway Variables, and only for a dedicated throwaway wallet.
