#!/usr/bin/env python3
"""
AI Phase 1 v3: Enhanced Dataset Generator
- 10,000 candles (100+ days of 15m data)
- 20 features (momentum, trend, volatility, price action, volume, time)
- Bollinger Bands, ATR, multi-period RSI, momentum
"""
import json
import sys
import urllib.request
import csv
import time
import math
from typing import List, Dict

# ============================================================
# INDICATORS
# ============================================================

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_ema(values, period):
    if len(values) < period:
        return sum(values) / len(values) if values else 0
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema

def calc_macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    fast_ema = calc_ema(closes, fast)
    slow_ema = calc_ema(closes, slow)
    macd_line = fast_ema - slow_ema
    macd_history = [fast_ema - slow_ema]
    ema_signal = calc_ema(macd_history, signal)
    return macd_line, ema_signal, macd_line - ema_signal

def calc_sma(values, period):
    if len(values) < period:
        return 0.0
    return sum(values[-period:]) / period

def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h, l = candles[i]["high"], candles[i]["low"]
        pc = candles[i-1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / period

def calc_bollinger(closes, period=20, std_mult=2):
    if len(closes) < period:
        return 0.0, 0.0, 0.0, 0.0
    sma = sum(closes[-period:]) / period
    variance = sum((c - sma) ** 2 for c in closes[-period:]) / period
    std = math.sqrt(variance)
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    width = (upper - lower) / sma if sma > 0 else 0
    return upper, lower, width, std

# ============================================================
# DATA FETCHING (paginated)
# ============================================================

def fetch_klines(symbol, interval, total_limit=10000):
    all_candles = []
    end_time = None
    requests_needed = (total_limit // 1000) + 1
    print(f"[INFO] Fetching {total_limit} candles in {requests_needed} batches...")

    for batch in range(requests_needed):
        batch_limit = min(1000, total_limit - len(all_candles))
        if batch_limit <= 0:
            break
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval={interval}&limit={batch_limit}"
        if end_time:
            url += f"&endTime={end_time}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
            if isinstance(data, dict) and data.get("code"):
                print(f"Error: {data.get('msg')}")
                break
            for k in data:
                all_candles.append({
                    "open_time": int(k[0]),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                })
            if len(data) > 0:
                end_time = data[0][0] - 1
            print(f"  Batch {batch+1}: +{len(data)} candles (total: {len(all_candles)})")
            time.sleep(0.3)
        except Exception as e:
            print(f"Batch error: {e}")
            if len(all_candles) > 1000:
                break
            sys.exit(1)

    all_candles.reverse()
    seen = set()
    unique = []
    for c in all_candles:
        if c["open_time"] not in seen:
            seen.add(c["open_time"])
            unique.append(c)
    print(f"[INFO] Total unique candles: {len(unique)}")
    return unique

# ============================================================
# FEATURE EXTRACTION
# ============================================================

FEATURE_NAMES = [
    "rsi_14", "rsi_7", "rsi_change", "macd_hist",
    "is_uptrend", "price_vs_sma50", "price_vs_sma200", "sma50_vs_sma200",
    "atr_pct", "bb_width", "bb_position",
    "candle_body", "wick_top", "wick_bot", "momentum_5", "momentum_10",
    "vol_change", "vol_price_trend",
    "hour_sin", "hour_cos",
]

def extract_features(candles, i):
    """Extract all 20 features for candle at index i"""
    c = candles[i]
    closes = [x["close"] for x in candles[:i+1]]

    # Momentum
    rsi_14 = calc_rsi(closes, 14)
    rsi_7 = calc_rsi(closes, 7)
    rsi_5_ago = calc_rsi(closes[:-5], 14) if len(closes) > 19 else rsi_14
    rsi_change = rsi_14 - rsi_5_ago
    _, _, macd_hist = calc_macd(closes, 12, 26, 9)

    # Trend
    sma50 = calc_sma(closes, 50)
    sma200 = calc_sma(closes, 200) if len(closes) >= 200 else sma50
    sma50_prev = calc_sma(closes[:-5], 50) if len(closes) >= 55 else sma50
    is_uptrend = 1 if sma50 > sma50_prev else 0
    price_vs_sma50 = (c["close"] - sma50) / sma50 if sma50 > 0 else 0
    price_vs_sma200 = (c["close"] - sma200) / sma200 if sma200 > 0 else 0
    sma50_vs_sma200 = (sma50 - sma200) / sma200 if sma200 > 0 else 0

    # Volatility
    atr = calc_atr(candles[:i+1], 14)
    atr_pct = atr / c["close"] if c["close"] > 0 else 0
    bb_upper, bb_lower, bb_width, bb_std = calc_bollinger(closes, 20)
    if bb_upper > bb_lower:
        bb_position = (c["close"] - bb_lower) / (bb_upper - bb_lower)
    else:
        bb_position = 0.5

    # Price Action
    body = (c["close"] - c["open"]) / c["open"] if c["open"] > 0 else 0
    wick_top = (c["high"] - max(c["open"], c["close"])) / c["open"] if c["open"] > 0 else 0
    wick_bot = (min(c["open"], c["close"]) - c["low"]) / c["open"] if c["open"] > 0 else 0
    mom_5 = (c["close"] - candles[i-5]["close"]) / candles[i-5]["close"] if i >= 5 else 0
    mom_10 = (c["close"] - candles[i-10]["close"]) / candles[i-10]["close"] if i >= 10 else 0

    # Volume
    current_vol = c["volume"]
    avg_vol_10 = sum(candles[j]["volume"] for j in range(i-10, i)) / 10 if i >= 10 else current_vol
    vol_change = (current_vol - avg_vol_10) / avg_vol_10 if avg_vol_10 > 0 else 0
    vol_price_trend = vol_change * (1 if c["close"] >= c["open"] else -1)

    # Time (cyclical encoding)
    hour = (c["open_time"] // 3600000) % 24
    hour_sin = math.sin(2 * math.pi * hour / 24)
    hour_cos = math.cos(2 * math.pi * hour / 24)

    return [
        round(rsi_14, 2),
        round(rsi_7, 2),
        round(rsi_change, 2),
        round(macd_hist, 4),
        is_uptrend,
        round(price_vs_sma50, 4),
        round(price_vs_sma200, 4),
        round(sma50_vs_sma200, 4),
        round(atr_pct, 4),
        round(bb_width, 4),
        round(bb_position, 4),
        round(body, 4),
        round(wick_top, 4),
        round(wick_bot, 4),
        round(mom_5, 4),
        round(mom_10, 4),
        round(vol_change, 2),
        round(vol_price_trend, 2),
        round(hour_sin, 4),
        round(hour_cos, 4),
    ]

# ============================================================
# MAIN
# ============================================================

def generate_csv(symbol, interval):
    candles = fetch_klines(symbol, interval, 10000)
    if len(candles) < 250:
        print("[ERROR] Not enough data.")
        return

    print(f"[INFO] Processing {len(candles)} candles into 20 ML features...")
    LOOK_AHEAD = 48
    TP_PCT = 0.025
    SL_PCT = 0.025

    rows = []
    start = 200  # Need 200 for SMA200
    for i in range(start, len(candles) - LOOK_AHEAD):
        features = extract_features(candles, i)

        # Target
        target = 0
        entry = candles[i]["close"]
        for j in range(1, LOOK_AHEAD + 1):
            future = candles[i + j]
            if future["high"] >= entry * (1 + TP_PCT):
                target = 1
                break
            if future["low"] <= entry * (1 - SL_PCT):
                target = 0
                break

        row = {"timestamp": candles[i]["open_time"]}
        for name, val in zip(FEATURE_NAMES, features):
            row[name] = val
        row["target"] = target
        rows.append(row)

    filename = f"{symbol.lower()}_{interval}_dataset.csv"
    fieldnames = ["timestamp"] + FEATURE_NAMES + ["target"]
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    wins = sum(1 for r in rows if r["target"] == 1)
    print(f"\n✅ Dataset saved to {filename}")
    print(f"Total rows: {len(rows)}")
    print(f"Features per row: {len(FEATURE_NAMES)}")
    print(f"Targets -> Wins (1): {wins} | Losses (0): {len(rows) - wins}")
    print(f"Win rate in dataset: {wins/len(rows)*100:.1f}%")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 generate_dataset.py <symbol> <interval>")
        sys.exit(1)
    generate_csv(sys.argv[1], sys.argv[2])
