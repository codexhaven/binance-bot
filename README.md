# Binance Trading Bot – CLI

A lightweight, **Python‑only** command‑line trading bot that works with Binance Spot and Futures.  
It can run in **paper‑trading** mode for strategy testing or in **live** mode for real orders.

## Table of Contents
- [Features](#features)  
- [Prerequisites](#prerequisites)  
- [Installation](#installation)  
- [Configuration](#configuration)  
- [Running the Bot](#running-the-bot)  
- [Command Reference](#command-reference)  
- [Project Structure](#project-structure)  
- [Testing & Debugging](#testing--debugging)  
- [License](#license)  

## Features
- **Real‑time kline streaming** via Binance WebSocket (`websocat`).
- **RSI** and **MACD** indicator calculations (pure Python, no heavy dependencies).
- **Paper‑trading engine** that simulates fills using order‑book depth snapshots.
- **Live order execution** (market, OCO, STOP‑MARKET) with proper step‑size / tick‑size handling.
- **Risk management**: position sizing, stop‑loss / take‑profit generation, dust conversion.
- **SQLite trade log** with CSV export for tax reporting.
- **Modular architecture** – each concern lives in its own file, making it easy to extend.

## Prerequisites
| Item | Minimum version | Why |
|------|----------------|-----|
| Python | 3.9+ | Standard library only; no external wheels required. |
| `curl` | any | Used by `api_client.py` to call Binance REST. |
| `websocat` | 1.9+ | Binary for Binance WebSocket streaming (install via package manager). |
| SQLite3 CLI | any | Persistent trade storage. |
| Binance API keys | – | Required for live mode (store in `.env`). |

### Android / Termux
If you are on Termux (aarch64), install the binaries with:

pkg install python curl sqlite websocat

## Installation
# Clone the repository
git clone https://github.com/yourname/binance-trading-bot.git
cd binance-trading-bot

# Create a virtual environment (optional but recommended)
python3 -m venv venv
source venv/bin/activate

# No external Python packages are required.
# Ensure the helper binaries are in $PATH
which curl websocat

## Configuration
Create a `.env` file in the project root (it is automatically ignored by `.gitignore`).

# .env – keep this file secret!
BINANCE_API_KEY=your_api_key_here
BINANCE_SECRET=your_secret_here

You can also adjust default risk parameters in `config.yaml` (generated on first run).

# config.yaml – default values, edit as needed
risk_percentage: 0.01          # 1 % of balance per trade
step_size: 0.00001             # Quantity step size for the symbol
min_notional: 5.0              # Minimum order value in USDT

## Running the Bot
The entry point is `cli.py`. Use the following syntax:

python3 cli.py <symbol> <interval> <mode>

- `symbol` – Binance symbol, e.g. `BTCUSDT`.
- `interval` – Kline interval (`1m`, `5m`, `15m`, `1h`, …).
- `mode` – `paper` for simulated trading or `live` for real orders.

### Example
python3 cli.py BTCUSDT 1m paper

The bot will:
1. Fetch the latest candle via REST to seed the stream.
2. Open a WebSocket to receive live candles.
3. Maintain a rolling list of closing prices.
4. Compute **RSI** (14‑period) and **MACD** (12‑26‑9) on each new close.
5. When RSI < 30 → **BUY**, RSI > 70 → **SELL** (simple demo strategy).
6. In paper mode, simulate fills using the current order‑book depth snapshot.
7. Log every trade to `trades.db` and print a concise summary to stdout.

Press `Ctrl‑C` to stop the bot gracefully; the SQLite DB remains intact.

## Command Reference
| Command | Description |
|---------|-------------|
| `python3 cli.py SYMBOL INTERVAL MODE` | Start the bot (see above). |
| `python3 trade_logger.py export <path>` | Export all logged trades to a CSV file at `<path>`. |
| `python3 risk_manager.py dust <ASSET>` | Convert dust for `<ASSET>` to BNB (live mode only). |
| `python3 api_client.py ping` | Simple health‑check that calls Binance `/api/v3/ping`. |

## Project Structure
.
├── api_client.py          # Low‑level Binance REST wrapper (curl)
├── kline_stream.py        # WebSocket handling & REST fallback
├── indicator.py           # RSI & MACD calculations
├── order_engine.py        # Market, OCO, STOP‑MARKET order helpers
├── risk_manager.py        # Position sizing, mark price, dust conversion
├── paper_trader.py        # Simulated fill engine & fee handling
├── trade_logger.py        # SQLite persistence + CSV export
├── cli.py                 # Main CLI entry point
├── config.yaml            # User‑editable defaults
├── .env                   # Secret keys (git‑ignored)
├── .gitignore             # Standard ignores + .env, .codex/, etc.
└── README.md              # ← you are here

All modules are **flat** (no sub‑folders) to keep the project simple and portable.

## Testing & Debugging
- **Syntax check**: `python3 -m py_compile *.py`
- **Dry‑run a market order** (paper mode) and inspect the SQLite DB:
  ```bash
  sqlite3 trades.db "SELECT * FROM trades ORDER BY ts DESC LIMIT 5;"
  ```
- **View raw WebSocket messages** (useful for troubleshooting):
  ```bash
  websocat -t "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
  ```

If you encounter a `curl` error, run the failing command manually (the command string is printed by `api_client._run_curl` on exception).

## License
MIT License – feel free to fork, modify, and use commercially.  
Please keep the original attribution header (`# ctx: codexhaven`) in each source file.

---  
*Happy trading!*