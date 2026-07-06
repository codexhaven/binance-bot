#!/usr/bin/env python3
"""
Backtesting Script - Test your strategy on historical data.
Usage: python3 backtest.py BTCUSDT 15m 1000
"""
import sys
import os
import json
import time
import subprocess
from typing import List

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from indicator import calc_rsi, calc_macd
from risk_manager import calc_position_size, calculate_sl_tp


def calc_sma(closes: List[float], period: int) -> float:
    if len(closes) < period:
        return 0.0
    return sum(closes[-period:]) / period


def is_uptrend(closes: List[float], period: int, lookback: int) -> bool:
    """Check if SMA is rising (current SMA > SMA from 'lookback' periods ago)."""
    if len(closes) < period + lookback:
        return False
    sma_now = sum(closes[-period:]) / period
    sma_prev = sum(closes[-(period + lookback):-lookback]) / period
    return sma_now > sma_prev


def fetch_historical_candles(symbol: str, interval: str, limit: int = 1000) -> List[list]:
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval={interval}&limit={limit}"
    try:
        raw = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=30).stdout
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("code"):
            print(f"[ERROR] {data.get('msg')}")
            return []
        return data
    except Exception as e:
        print(f"[ERROR] Fetch failed: {e}")
        return []


def backtest(symbol: str, interval: str, num_candles: int):
    trend_str = f" + Trend(SMA{config.TREND_SMA_PERIOD} slope)" if config.USE_TREND_FILTER else ""
    print("=" * 65)
    print(f"  BACKTEST: {symbol} {interval} | {num_candles} candles")
    print(f"  Strategy: RSI<{config.RSI_OVERSOLD} BUY, RSI>{config.RSI_OVERBOUGHT} SELL{trend_str}")
    print(f"  SL: {config.STOP_LOSS_PCT*100:.1f}% | TP: {config.TAKE_PROFIT_PCT*100:.1f}%"
          + (f" | Trail: {config.TRAILING_STOP_PCT*100:.1f}%" if config.USE_TRAILING_STOP else ""))
    print(f"  Risk: {config.RISK_PER_TRADE*100:.1f}% | Fee: {config.TRADING_FEE_PCT*100:.2f}%")
    print("=" * 65)

    candles = fetch_historical_candles(symbol, interval, num_candles)
    if not candles:
        print("[ERROR] No data fetched.")
        return

    print(f"\n[INFO] Fetched {len(candles)} candles.")
    print(f"[INFO] Period: {time.strftime('%Y-%m-%d %H:%M', time.localtime(candles[0][0]/1000))}"
          f" -> {time.strftime('%Y-%m-%d %H:%M', time.localtime(candles[-1][0]/1000))}")

    closes = []
    balance = config.PAPER_BALANCE
    initial_balance = balance
    in_position = False
    entry_price = 0.0
    qty = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    highest_since_entry = 0.0
    trades = []
    wins = 0
    losses = 0
    signal_exits = 0
    sl_exits = 0
    tp_exits = 0
    skipped_by_trend = 0

    for candle in candles:
        close_time = candle[6]
        close_price = float(candle[4])
        high_price = float(candle[2])
        low_price = float(candle[3])
        closes.append(close_price)
        if len(closes) > 200:
            closes.pop(0)
        if len(closes) < config.MIN_CANDLES_FOR_SIGNAL:
            continue
        try:
            rsi = calc_rsi(closes, period=14)
        except Exception:
            continue

        uptrend = True
        if config.USE_TREND_FILTER:
            uptrend = is_uptrend(closes, config.TREND_SMA_PERIOD, config.TREND_SLOPE_LOOKBACK)

        if in_position:
            if high_price > highest_since_entry:
                highest_since_entry = high_price
            if config.USE_TRAILING_STOP:
                new_sl = highest_since_entry * (1 - config.TRAILING_STOP_PCT)
                if new_sl > stop_loss:
                    stop_loss = new_sl
            exit_price = None
            exit_reason = None
            if low_price <= stop_loss:
                exit_price = stop_loss
                exit_reason = "SL"
                sl_exits += 1
            elif high_price >= take_profit:
                exit_price = take_profit
                exit_reason = "TP"
                tp_exits += 1
            elif rsi > config.RSI_OVERBOUGHT:
                exit_price = close_price
                exit_reason = "SIG"
                signal_exits += 1
            if exit_price:
                gross = exit_price * qty
                fee = gross * config.TRADING_FEE_PCT
                net = gross - fee
                cost = entry_price * qty
                pnl = net - cost
                balance += pnl
                pnl_pct = (pnl / cost) * 100
                trades.append({
                    "entry": entry_price, "exit": exit_price, "qty": qty,
                    "pnl": pnl, "pnl_pct": pnl_pct, "reason": exit_reason,
                    "time": time.strftime("%m-%d %H:%M", time.localtime(close_time/1000)),
                })
                if pnl > 0: wins += 1
                else: losses += 1
                in_position = False
                entry_price = 0.0
                qty = 0.0
                continue

        if not in_position and len(closes) >= config.MIN_CANDLES_FOR_SIGNAL:
            if rsi < config.RSI_OVERSOLD:
                if config.USE_TREND_FILTER and not uptrend:
                    skipped_by_trend += 1
                    continue
                qty = calc_position_size(
                    balance=balance, price=close_price,
                    risk_pct=config.RISK_PER_TRADE,
                    step_size=config.STEP_SIZE,
                    min_notional=config.MIN_NOTIONAL,
                )
                if qty <= 0:
                    continue
                cost = close_price * qty
                fee = cost * config.TRADING_FEE_PCT
                balance -= fee
                entry_price = close_price
                in_position = True
                levels = calculate_sl_tp(close_price, "BUY", config.STOP_LOSS_PCT, config.TAKE_PROFIT_PCT)
                stop_loss = levels["sl"]
                take_profit = levels["tp"]
                highest_since_entry = close_price

    print("\n" + "=" * 65)
    print("  BACKTEST RESULTS")
    print("=" * 65)
    total_trades = len(trades)
    if total_trades == 0:
        print("\n  No trades were executed.")
        if skipped_by_trend:
            print(f"  ({skipped_by_trend} signals skipped by trend filter)")
        return
    total_pnl = balance - initial_balance
    win_rate = (wins / total_trades) * 100 if total_trades else 0
    print(f"\n  Initial Balance:  {initial_balance:.2f} USDT")
    print(f"  Final Balance:    {balance:.2f} USDT")
    print(f"  Total PnL:        {total_pnl:+.2f} USDT ({(total_pnl/initial_balance)*100:+.2f}%)")
    print(f"  Total Trades:     {total_trades}")
    print(f"  Wins:             {wins}")
    print(f"  Losses:           {losses}")
    print(f"  Win Rate:         {win_rate:.1f}%")
    print(f"\n  Exit breakdown:   {tp_exits} take-profit, {sl_exits} stop-loss, {signal_exits} signal")
    if skipped_by_trend:
        print(f"  Trend filtered:   {skipped_by_trend} signals skipped (downtrend)")
    if trades:
        best = max(trades, key=lambda t: t["pnl"])
        worst = min(trades, key=lambda t: t["pnl"])
        print(f"\n  Best Trade:       {best['pnl']:+.2f} USDT ({best['pnl_pct']:+.2f}%) [{best['reason']}] @ {best['time']}")
        print(f"  Worst Trade:      {worst['pnl']:+.2f} USDT ({worst['pnl_pct']:+.2f}%) [{worst['reason']}] @ {worst['time']}")
        avg_win = sum(t["pnl"] for t in trades if t["pnl"] > 0) / wins if wins else 0
        avg_loss = sum(t["pnl"] for t in trades if t["pnl"] <= 0) / losses if losses else 0
        print(f"  Avg Win:          {avg_win:+.2f} USDT")
        print(f"  Avg Loss:         {avg_loss:+.2f} USDT")
    print("\n" + "-" * 65)
    print("  TRADE LOG:")
    print("-" * 65)
    print(f"  {'Time':<12} {'Entry':>10} {'Exit':>10} {'Qty':>10} {'PnL':>10} {'%':>8} {'Reason':<6}")
    print("-" * 65)
    for t in trades:
        print(f"  {t['time']:<12} {t['entry']:>10.2f} {t['exit']:>10.2f} {t['qty']:>10.6f} {t['pnl']:>+10.2f} {t['pnl_pct']:>+7.2f}% {t['reason']:<6}")
    print("\n" + "=" * 65)
    if total_pnl > 0:
        print("  ✅ Strategy is PROFITABLE on this data set")
    else:
        print("  ❌ Strategy is NOT profitable on this data set")
        print("  Try: adjusting RSI thresholds, SL/TP %, or interval in config.py")
    print("=" * 65)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python3 backtest.py <symbol> <interval> <num_candles>")
        sys.exit(1)
    backtest(sys.argv[1], sys.argv[2], int(sys.argv[3]))
