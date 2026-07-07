#!/usr/bin/env python3
"""
AI Phase 3: Live Predictor Module
Loads the trained Random Forest model and makes real-time predictions.
"""
import pickle
import math
import os
import config
from typing import List, Dict, Tuple

# ============================================================
# INDICATORS (must match generate_dataset.py exactly)
# ============================================================

def _calc_rsi(closes, period=14):
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

def _calc_ema(values, period):
    if len(values) < period:
        return sum(values) / len(values) if values else 0
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema

def _calc_macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    fast_ema = _calc_ema(closes, fast)
    slow_ema = _calc_ema(closes, slow)
    macd_line = fast_ema - slow_ema
    macd_history = [fast_ema - slow_ema]
    ema_signal = _calc_ema(macd_history, signal)
    return macd_line, ema_signal, macd_line - ema_signal

def _calc_sma(values, period):
    if len(values) < period:
        return 0.0
    return sum(values[-period:]) / period

def _calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h, l = candles[i]["high"], candles[i]["low"]
        pc = candles[i-1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / period

def _calc_bollinger(closes, period=20, std_mult=2):
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
# FEATURE EXTRACTION (must match generate_dataset.py exactly)
# ============================================================

FEATURE_NAMES = [
    "rsi_14", "rsi_7", "rsi_change", "macd_hist",
    "is_uptrend", "price_vs_sma50", "price_vs_sma200", "sma50_vs_sma200",
    "atr_pct", "bb_width", "bb_position",
    "candle_body", "wick_top", "wick_bot", "momentum_5", "momentum_10",
    "vol_change", "vol_price_trend",
    "hour_sin", "hour_cos",
]

def extract_features(candles: List[Dict], i: int) -> List[float]:
    c = candles[i]
    closes = [x["close"] for x in candles[:i+1]]

    rsi_14 = _calc_rsi(closes, 14)
    rsi_7 = _calc_rsi(closes, 7)
    rsi_5_ago = _calc_rsi(closes[:-5], 14) if len(closes) > 19 else rsi_14
    rsi_change = rsi_14 - rsi_5_ago
    _, _, macd_hist = _calc_macd(closes, 12, 26, 9)

    sma50 = _calc_sma(closes, 50)
    sma200 = _calc_sma(closes, 200) if len(closes) >= 200 else sma50
    sma50_prev = _calc_sma(closes[:-5], 50) if len(closes) >= 55 else sma50
    is_uptrend = 1 if sma50 > sma50_prev else 0
    price_vs_sma50 = (c["close"] - sma50) / sma50 if sma50 > 0 else 0
    price_vs_sma200 = (c["close"] - sma200) / sma200 if sma200 > 0 else 0
    sma50_vs_sma200 = (sma50 - sma200) / sma200 if sma200 > 0 else 0

    atr = _calc_atr(candles[:i+1], 14)
    atr_pct = atr / c["close"] if c["close"] > 0 else 0
    bb_upper, bb_lower, bb_width, _ = _calc_bollinger(closes, 20)
    bb_position = (c["close"] - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5

    body = (c["close"] - c["open"]) / c["open"] if c["open"] > 0 else 0
    wick_top = (c["high"] - max(c["open"], c["close"])) / c["open"] if c["open"] > 0 else 0
    wick_bot = (min(c["open"], c["close"]) - c["low"]) / c["open"] if c["open"] > 0 else 0
    mom_5 = (c["close"] - candles[i-5]["close"]) / candles[i-5]["close"] if i >= 5 else 0
    mom_10 = (c["close"] - candles[i-10]["close"]) / candles[i-10]["close"] if i >= 10 else 0

    current_vol = c["volume"]
    avg_vol_10 = sum(candles[j]["volume"] for j in range(i-10, i)) / 10 if i >= 10 else current_vol
    vol_change = (current_vol - avg_vol_10) / avg_vol_10 if avg_vol_10 > 0 else 0
    vol_price_trend = vol_change * (1 if c["close"] >= c["open"] else -1)

    hour = (c["open_time"] // 3600000) % 24
    hour_sin = math.sin(2 * math.pi * hour / 24)
    hour_cos = math.cos(2 * math.pi * hour / 24)

    return [
        round(rsi_14, 2), round(rsi_7, 2), round(rsi_change, 2),
        round(macd_hist, 4), is_uptrend,
        round(price_vs_sma50, 4), round(price_vs_sma200, 4),
        round(sma50_vs_sma200, 4), round(atr_pct, 4),
        round(bb_width, 4), round(bb_position, 4),
        round(body, 4), round(wick_top, 4), round(wick_bot, 4),
        round(mom_5, 4), round(mom_10, 4),
        round(vol_change, 2), round(vol_price_trend, 2),
        round(hour_sin, 4), round(hour_cos, 4),
    ]

# ============================================================
# AI PREDICTOR
# ============================================================

class AIPredictor:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.trees = None
        self.threshold = 0.80
        self.features = FEATURE_NAMES
        self._loaded = False
        self._load()

    def _load(self):
        model_file = f"{self.symbol.lower()}_model.pkl"
        if not os.path.exists(model_file):
            print(f"[AI] ⚠️  No model found: {model_file}")
            print(f"[AI]    Run: python3 train_model.py {self.symbol.lower()}_15m_dataset.csv")
            return

        try:
            with open(model_file, "rb") as f:
                data = pickle.load(f)
            self.trees = data['trees']
            self.features = data['features']
            self.threshold = getattr(config, "AI_THRESHOLD", data.get('threshold', 0.80))
            self._loaded = True
            print(f"[AI] ✅ Loaded {self.symbol} model ({len(self.trees)} trees, threshold: {self.threshold*100:.0f}%)")
        except Exception as e:
            print(f"[AI] ❌ Failed to load model: {e}")

    def predict(self, candles: List[Dict]) -> Tuple[bool, float]:
        """Returns (should_buy, probability)"""
        if not self.trees or not self._loaded:
            return False, 0.0
        if len(candles) < 200:
            return False, 0.0

        features = extract_features(candles, len(candles) - 1)

        probas = []
        for tree in self.trees:
            # tree is a plain dict (the tree structure)
            node = tree
            # Handle both dict and object formats
            if hasattr(node, 'tree'):
                node = node.tree
            while not node['leaf']:
                if features[node['feature']] <= node['threshold']:
                    node = node['left']
                else:
                    node = node['right']
            probas.append(node['proba'])

        probability = sum(probas) / len(probas)
        should_buy = probability >= self.threshold

        return should_buy, probability
