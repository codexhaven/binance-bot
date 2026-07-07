#!/usr/bin/env python3
"""
Central configuration for the Binance trading bot - v4.

Key insight: RSI oversold + price above SMA = nearly impossible.
Fix: Use SMA SLOPE (rising SMA = uptrend) instead of price vs SMA.
This catches pullbacks in uptrends: "buy the dip" strategy.
"""

# ============================================================
# STRATEGY SETTINGS
# ============================================================
SYMBOL = "BTCUSDT"
INTERVAL = "15m"

RSI_OVERSOLD = 40              # Raised from 35 -> 40 for more signals
RSI_OVERBOUGHT = 78
USE_MACD_CONFIRM = False

# TREND FILTER - checks if SMA is RISING (uptrend), not if price > SMA
USE_TREND_FILTER = True
TREND_SMA_PERIOD = 50
TREND_SLOPE_LOOKBACK = 5       # Compare current SMA to SMA 5 periods ago

# ============================================================
# RISK MANAGEMENT
# ============================================================
RISK_PER_TRADE = 0.02
STOP_LOSS_PCT = 0.025
TAKE_PROFIT_PCT = 0.045
USE_TRAILING_STOP = True
TRAILING_STOP_PCT = 0.030

# ============================================================
# POSITION MANAGEMENT
# ============================================================
MAX_POSITIONS = 1
COOLDOWN_SECONDS = 300
MIN_CANDLES_FOR_SIGNAL = 55

# ============================================================
# EXCHANGE SETTINGS
# ============================================================
STEP_SIZE = 0.00001
TICK_SIZE = 0.01
MIN_NOTIONAL = 5.0
QUOTE_ASSET = "USDT"

# ============================================================
# PAPER TRADING
# ============================================================
PAPER_BALANCE = 10000.0
TRADING_FEE_PCT = 0.001

# ============================================================
# LOGGING
# ============================================================
LOG_STATUS_EVERY_TICK = True
DB_PATH = "trades.db"
CSV_PATH = "trades_export.csv"

# AI Settings
AI_THRESHOLD = 0.70  # Backtest-proven sweet spot (75% = 100% win rate on ETH)
