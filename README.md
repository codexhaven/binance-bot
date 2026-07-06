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
- **RSI strategy with Trend Filter** — Buys oversold dips only when the SMA is rising (uptrend).
- **Full Risk Management** — Position sizing, stop‑loss, take‑profit, and a trailing stop that locks in gains.
- **Signal‑Based Exits** — Automatically sells when RSI becomes overbought.
- **Backtesting Engine** — Test your strategy on historical candles before risking real money.
- **Trade Dashboard** — View your trade history and P&L in the terminal.
- **Real‑time kline streaming** via Binance WebSocket (`websocat`).
- **Paper‑trading engine** that simulates fills using order‑book depth snapshots.
- **Live order execution** (market, OCO, STOP‑MARKET) with proper step‑size / tick‑size handling.
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
```bash
pkg install python curl sqlite websocat
Installation
# Clone the repository
git clone https://github.com/codexhaven/binance-bot.git
cd binance-bot
# Create a virtual environment (optional but recommended)
python3 -m venv venv
source venv/bin/activate
# No external Python packages are required.
# Ensure the helper binaries are in $PATH
which curl websocat
Configuration
Create a .env file in the project root (it is automatically ignored by .gitignore).
# .env – keep this file secret!
BINANCE_API_KEY=your_api_key_here
BINANCE_SECRET=your_secret_here
All strategy and risk parameters are centralized in config.py. Edit this file to tune the bot:
# config.py – default values, edit as needed
# Strategy
INTERVAL = "15m"
RSI_OVERSOLD = 40
RSI_OVERBOUGHT = 70
USE_TREND_FILTER = True
TREND_SMA_PERIOD = 50
# Risk Management
RISK_PER_TRADE = 0.02          # 2% of balance per trade
STOP_LOSS_PCT = 0.035          # 3.5% stop loss
TAKE_PROFIT_PCT = 0.025        # 2.5% take profit
TRAILING_STOP_PCT = 0.025      # 2.5% trailing stop
Running the Bot
1. Backtest First
Always test your strategy on historical data before running live:
python3 backtest.py BTCUSDT 15m 1000
2. Run the Bot
The entry point is cli.py. Use the following syntax:
python3 cli.py <symbol> <interval> <mode>
symbol – Binance symbol, e.g. BTCUSDT.
interval – Kline interval (1m, 5m, 15m, 1h, …).
mode – paper for simulated trading or live for real orders.
Example:
python3 cli.py BTCUSDT 15m paper
The bot will:
Fetch recent candle history via REST to seed indicators.
Open a WebSocket to receive live candle closes.
Maintain a rolling list of closing prices.
Compute RSI (14‑period), MACD (12‑26‑9), and SMA50 on each new close.
Entry: If RSI < 40 AND SMA50 is rising → BUY.
Exit: If Stop‑Loss hit OR Take‑Profit hit OR RSI > 70 OR Trailing Stop hit → SELL.
In paper mode, simulate fills using the current order‑book depth snapshot.
Log every trade to trades.db and print a concise summary to stdout.
Press Ctrl‑C to stop the bot gracefully; the SQLite DB remains intact.
3. View Trade History
Use the dashboard to view your trade history and export to CSV:
python3 dashboard.py
Command Reference
Command	Description	
python3 backtest.py SYMBOL INTERVAL NUM_CANDLES	Run a backtest on historical data (e.g., BTCUSDT 15m 1000).	
python3 cli.py SYMBOL INTERVAL MODE	Start the live/paper trading bot.	
python3 dashboard.py	View trade history, P&L, and export CSV.	
python3 trade_logger.py export <path>	Export all logged trades to a CSV file at <path>.	
python3 risk_manager.py dust <ASSET>	Convert dust for <ASSET> to BNB (live mode only).	
python3 api_client.py ping	Simple health‑check that calls Binance /api/v3/ping.	
Project Structure
.
├── api_client.py          # Low‑level Binance REST wrapper (curl)
├── kline_stream.py        # WebSocket handling & REST fallback
├── indicator.py           # RSI, MACD & SMA calculations
├── order_engine.py        # Market, OCO, STOP‑MARKET order helpers
├── risk_manager.py        # Position sizing, mark price, dust conversion
├── paper_trader.py        # Simulated fill engine & fee handling
├── trade_logger.py        # SQLite persistence + CSV export
├── backtest.py            # Historical strategy backtester
├── dashboard.py           # Terminal dashboard for trade history
├── cli.py                 # Main CLI entry point
├── config.py              # Centralized configuration (strategy & risk)
├── .env                   # Secret keys (git‑ignored)
├── .gitignore             # Standard ignores + .env, .codex/, etc.
└── README.md              # ← you are here
All modules are flat (no sub‑folders) to keep the project simple and portable.
Testing & Debugging
Syntax check: python3 -m py_compile *.py
Dry‑run a market order (paper mode) and inspect the SQLite DB:sqlite3 trades.db "SELECT * FROM trades ORDER BY ts DESC LIMIT 5;"
View raw WebSocket messages (useful for troubleshooting):websocat -t "wss://stream.binance.com:9443/ws/btcusdt@kline_15m"
If you encounter a curl error, run the failing command manually (the command string is printed by api_client._run_curl on exception).
License
MIT License – feel free to fork, modify, and use commercially.
Please keep the original attribution header (# ctx: codexhaven) in each source file.
Happy trading!
