#!/usr/bin/env python3
"""
AI Backtest v2: Tests multiple thresholds on fresh data.
Fetches 1000 candles (10 days) the model has NEVER seen.
"""
import sys
import json
import urllib.request
import math
from ai_predictor import AIPredictor, extract_features

def fetch_klines(symbol, interval, limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    candles = []
    for k in data:
        candles.append({
            "open_time": int(k[0]), "open": float(k[1]),
            "high": float(k[2]), "low": float(k[3]),
            "close": float(k[4]), "volume": float(k[5]),
        })
    return candles

def run_backtest_at_threshold(ai, candles, threshold, sl_pct=0.025, tp_pct=0.025, max_holding=48):
    """Run backtest at a specific threshold"""
    balance = 10000.0
    risk_pct = 0.02
    trades = []
    in_position = False
    entry_price = 0
    qty = 0
    stop_loss = 0
    take_profit = 0
    entry_idx = 0

    for i in range(200, len(candles)):
        c = candles[i]

        if in_position:
            exit_price = None
            exit_reason = None
            if c["low"] <= stop_loss:
                exit_price = stop_loss
                exit_reason = "SL"
            elif c["high"] >= take_profit:
                exit_price = take_profit
                exit_reason = "TP"
            elif i - entry_idx >= max_holding:
                exit_price = c["close"]
                exit_reason = "TIME"

            if exit_price:
                pnl = (exit_price - entry_price) * qty - (entry_price * qty * 0.001 + exit_price * qty * 0.001)
                balance += pnl
                trades.append({
                    "entry": entry_price, "exit": exit_price,
                    "pnl": pnl, "pnl_pct": pnl / (entry_price * qty) * 100,
                    "reason": exit_reason, "proba": entry_proba,
                })
                in_position = False

        if not in_position:
            features = extract_features(candles[:i+1], i)
            probas = []
            for tree in ai.trees:
                node = tree
                while not node['leaf']:
                    if features[node['feature']] <= node['threshold']:
                        node = node['left']
                    else:
                        node = node['right']
                probas.append(node['proba'])
            proba = sum(probas) / len(probas)

            if proba >= threshold:
                entry_price = c["close"]
                entry_idx = i
                entry_proba = proba
                risk_amount = balance * risk_pct
                qty = risk_amount / (entry_price * sl_pct)
                stop_loss = entry_price * (1 - sl_pct)
                take_profit = entry_price * (1 + tp_pct)
                in_position = True

    return balance, trades

def run_backtest(symbol, interval):
    print(f"\n{'='*60}")
    print(f"  AI BACKTEST: {symbol} {interval}")
    print(f"{'='*60}")

    ai = AIPredictor(symbol)
    if not ai.trees:
        print("  ❌ No model loaded.")
        return

    print(f"\n  Fetching 1000 recent candles (10 days)...")
    candles = fetch_klines(symbol, interval, 1000)
    print(f"  Got {len(candles)} candles")

    # Test multiple thresholds
    print(f"\n{'='*60}")
    print(f"  THRESHOLD COMPARISON ON FRESH DATA")
    print(f"{'='*60}")
    print(f"  {'Threshold':>10} | {'Trades':>7} | {'Wins':>5} | {'Win%':>6} | {'PnL':>10} | {'ROI':>7}")
    print(f"  {'-'*10}-+-{'-'*7}-+-{'-'*5}-+-{'-'*6}-+-{'-'*10}-+-{'-'*7}")

    best_roi = -999
    best_thresh = 0.70
    best_trades = []

    for thresh in [0.70, 0.75, 0.80, 0.85]:
        balance, trades = run_backtest_at_threshold(ai, candles, thresh)
        wins = [t for t in trades if t["pnl"] > 0]
        roi = (balance - 10000) / 10000 * 100
        wr = len(wins) / len(trades) * 100 if trades else 0
        pnl_str = f"{balance-10000:+.2f}"
        print(f"  {thresh*100:>9.0f}% | {len(trades):>7} | {len(wins):>5} | {wr:>5.1f}% | {pnl_str:>10} | {roi:>+6.2f}%")
        if roi > best_roi and len(trades) >= 2:
            best_roi = roi
            best_thresh = thresh
            best_trades = trades

    print(f"\n  Best: {best_thresh*100:.0f}% threshold (ROI: {best_roi:+.2f}%)")

    # Show trade details for best threshold
    if best_trades:
        from datetime import datetime
        print(f"\n{'='*60}")
        print(f"  TRADE DETAILS ({best_thresh*100:.0f}% threshold)")
        print(f"{'='*60}")
        print(f"  {'#':>3} | {'Entry':>10} | {'Exit':>10} | {'PnL':>8} | {'%':>6} | {'Reason':>6} | {'Proba':>6}")
        print(f"  {'-'*3}-+-{'-'*10}-+-{'-'*10}-+-{'-'*8}-+-{'-'*6}-+-{'-'*6}-+-{'-'*6}")
        for idx, t in enumerate(best_trades):
            print(f"  {idx+1:>3} | {t['entry']:>10.2f} | {t['exit']:>10.2f} | {t['pnl']:>+8.2f} | {t['pnl_pct']:>+5.2f}% | {t['reason']:>6} | {t['proba']*100:>5.1f}%")

    # Also show what the AI sees RIGHT NOW
    print(f"\n{'='*60}")
    print(f"  LIVE AI READOUT (Current Market)")
    print(f"{'='*60}")
    features = extract_features(candles, len(candles) - 1)
    probas = []
    for tree in ai.trees:
        node = tree
        while not node['leaf']:
            if features[node['feature']] <= node['threshold']:
                node = node['left']
            else:
                node = node['right']
        probas.append(node['proba'])
    live_proba = sum(probas) / len(probas)
    print(f"  Symbol: {symbol}")
    print(f"  Price: ${candles[-1]['close']:.2f}")
    print(f"  AI Confidence: {live_proba*100:.1f}%")
    print(f"  Threshold: {best_thresh*100:.0f}%")
    if live_proba >= best_thresh:
        print(f"  Signal: 🟢 BUY")
    else:
        print(f"  Signal: 🔴 WAIT (need {best_thresh*100:.0f}%, got {live_proba*100:.1f}%)")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 ai_backtest.py <symbol> <interval>")
        sys.exit(1)
    run_backtest(sys.argv[1], sys.argv[2])
