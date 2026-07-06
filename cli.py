#!/usr/bin/env python3
"""
Binance Trading Bot - Enhanced Edition v4
=========================================
Strategy: Buy oversold dips in uptrends (SMA rising)
"""
import sys
import os
import json
import time
import threading
import queue
import subprocess
from typing import List, Optional, Dict, Any

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from kline_stream import start_kline_ws
from indicator import calc_rsi, calc_macd
from risk_manager import calc_position_size, calculate_sl_tp
from order_engine import place_market_order
from paper_trader import simulate_market_fill, apply_fees
from trade_logger import init_db, log_trade, get_last_trade
from api_client import curl_get


def load_env():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

load_env()


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


class Position:
    def __init__(self):
        self.in_position = False
        self.side = None
        self.entry_price = 0.0
        self.qty = 0.0
        self.entry_ts = 0
        self.stop_loss = 0.0
        self.take_profit = 0.0
        self.highest_since_entry = 0.0

    def open(self, entry_price: float, qty: float, side: str = "LONG"):
        self.in_position = True
        self.side = side
        self.entry_price = entry_price
        self.qty = qty
        self.entry_ts = int(time.time() * 1000)
        self.highest_since_entry = entry_price
        self._set_sl_tp(entry_price)

    def close(self):
        self.in_position = False
        self.side = None
        self.entry_price = 0.0
        self.qty = 0.0
        self.stop_loss = 0.0
        self.take_profit = 0.0
        self.highest_since_entry = 0.0

    def _set_sl_tp(self, price: float):
        levels = calculate_sl_tp(
            entry_price=price, side="BUY",
            sl_pct=config.STOP_LOSS_PCT, tp_pct=config.TAKE_PROFIT_PCT,
        )
        self.stop_loss = levels["sl"]
        self.take_profit = levels["tp"]

    def update_trailing(self, current_price: float):
        if current_price > self.highest_since_entry:
            self.highest_since_entry = current_price
        if config.USE_TRAILING_STOP:
            new_sl = self.highest_since_entry * (1 - config.TRAILING_STOP_PCT)
            if new_sl > self.stop_loss:
                self.stop_loss = new_sl

    def check_exit(self, current_price: float, rsi: float) -> Optional[str]:
        if not self.in_position:
            return None
        if current_price <= self.stop_loss:
            return "SL"
        if current_price >= self.take_profit:
            return "TP"
        if rsi > config.RSI_OVERBOUGHT:
            return "SIG"
        return None


def fetch_real_balance(api_key: str, secret: str, asset: str = "USDT") -> float:
    try:
        params = {"recvWindow": "5000"}
        url = "https://api.binance.com/api/v3/account"
        resp_str = curl_get(url, api_key, secret, params)
        data = json.loads(resp_str)
        if isinstance(data, dict) and data.get("code"):
            print(f"[ERROR] Binance balance API error: {data.get('msg')}", file=sys.stderr)
            return 0.0
        for bal in data.get("balances", []):
            if bal.get("asset") == asset:
                return float(bal.get("free", 0))
        return 0.0
    except Exception as e:
        print(f"[ERROR] Failed to fetch balance: {e}", file=sys.stderr)
        return 0.0


def fetch_recent_closes(symbol: str, interval: str, count: int = 200) -> List[float]:
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval={interval}&limit={count}"
    try:
        raw = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=15).stdout
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("code"):
            print(f"[ERROR] Binance klines error: {data.get('msg')}", file=sys.stderr)
            return []
        return [float(k[4]) for k in data]
    except Exception as e:
        print(f"[ERROR] Failed to fetch closes: {e}", file=sys.stderr)
        return []


def evaluate_signal(closes: List[float]) -> Optional[str]:
    if len(closes) < config.MIN_CANDLES_FOR_SIGNAL:
        return None
    try:
        rsi = calc_rsi(closes, period=14)
    except Exception as e:
        print(f"[WARN] Indicator calc error: {e}", file=sys.stderr)
        return None
    if rsi < config.RSI_OVERSOLD:
        if config.USE_TREND_FILTER:
            if not is_uptrend(closes, config.TREND_SMA_PERIOD, config.TREND_SLOPE_LOOKBACK):
                return None
        return "BUY"
    return None


def candle_callback_factory(price_queue: queue.Queue):
    def candle_cb(*args):
        try:
            if len(args) >= 5:
                c = float(args[4])
            elif len(args) == 1:
                cd = args[0]
                if isinstance(cd, dict):
                    c = float(cd.get("c", cd.get("close", 0)))
                elif isinstance(cd, (list, tuple)):
                    c = float(cd[4]) if len(cd) > 4 else 0
                else:
                    c = float(cd)
            else:
                return
            if c > 0:
                price_queue.put_nowait(c)
        except queue.Full:
            pass
        except Exception:
            pass
    return candle_cb


def execute_trade(
    symbol: str, side: str, qty: float, price: float,
    mode: str, api_key: str, secret: str, reason: str = "SIGNAL",
) -> Optional[Dict[str, Any]]:
    ts = int(time.time() * 1000)
    if mode == "paper":
        depth = json.dumps({"bids": [[price, qty]], "asks": [[price, qty]]})
        try:
            fill_price = simulate_market_fill(symbol, side, qty, depth)
            gross = fill_price * qty
            net_total = apply_fees(gross, is_futures=False)
            fee = gross - net_total
            net_price = net_total / qty if qty else price
        except Exception as e:
            print(f"[ERROR] Paper fill failed: {e}", file=sys.stderr)
            return None
        order_id = "simulated"
        avg_price = net_price
    else:
        try:
            resp = place_market_order(symbol, side, qty, api_key, secret, step_size=config.STEP_SIZE)
            if isinstance(resp, dict) and resp.get("code") and resp.get("code") != 200:
                print(f"[ERROR] Order rejected: {resp.get('msg')}", file=sys.stderr)
                return None
            fills = resp.get("fills", [])
            if fills:
                total_qty = sum(float(f["qty"]) for f in fills)
                avg_price = sum(float(f["price"]) * float(f["qty"]) for f in fills) / total_qty if total_qty else price
            else:
                avg_price = price
            fee = sum(float(f.get("commission", 0)) for f in fills)
            order_id = str(resp.get("orderId", "unknown"))
        except Exception as e:
            print(f"[ERROR] Live order failed: {e}", file=sys.stderr)
            return None
    try:
        log_trade(
            ts=ts, symbol=symbol, side=side, qty=qty, price=avg_price,
            fee=fee, fee_asset="USDT", realized_pnl=0.0, mode=mode, order_id=order_id,
        )
    except Exception as e:
        print(f"[ERROR] Failed to log trade: {e}", file=sys.stderr)
    result = {"price": avg_price, "qty": qty, "fee": fee, "order_id": order_id}
    tag = "PAPER" if mode == "paper" else "LIVE"
    print(f"  [{tag}] {reason} -> {side} {qty:.6f} {symbol} @ {avg_price:.2f} (fee: {fee:.4f} USDT, id: {order_id})")
    return result


def run_bot(symbol: str, interval: str, mode: str, api_key: str, secret: str) -> None:
    if mode not in ("paper", "live"):
        print("[ERROR] Mode must be 'paper' or 'live'.", file=sys.stderr)
        return
    trend_str = f" + Trend(SMA{config.TREND_SMA_PERIOD} slope)" if config.USE_TREND_FILTER else ""
    print("=" * 65)
    print("  BINANCE TRADING BOT - ENHANCED EDITION v4")
    print(f"  Symbol: {symbol}  |  Interval: {interval}  |  Mode: {mode.upper()}")
    print(f"  Strategy: RSI<{config.RSI_OVERSOLD} BUY, RSI>{config.RSI_OVERBOUGHT} SELL{trend_str}")
    print(f"  Risk: {config.RISK_PER_TRADE*100:.1f}%/trade  |  SL: {config.STOP_LOSS_PCT*100:.1f}%  |  TP: {config.TAKE_PROFIT_PCT*100:.1f}%")
    if config.USE_TRAILING_STOP:
        print(f"  Trailing stop: {config.TRAILING_STOP_PCT*100:.1f}% from peak")
    print(f"  Cooldown: {config.COOLDOWN_SECONDS}s  |  Max positions: {config.MAX_POSITIONS}")
    print("=" * 65)
    try:
        init_db()
    except Exception as e:
        print(f"[ERROR] DB init failed: {e}", file=sys.stderr)
        return
    position = Position()
    last_trade_ts = 0
    price_q: queue.Queue = queue.Queue(maxsize=10)
    candle_cb = candle_callback_factory(price_q)
    try:
        threading.Thread(target=start_kline_ws, args=(symbol.lower(), interval, candle_cb), daemon=True).start()
    except Exception as e:
        print(f"[ERROR] WS start failed: {e}", file=sys.stderr)
    print(f"\n[INFO] Fetching {symbol} candle history...")
    recent_closes = fetch_recent_closes(symbol, interval, count=200)
    if recent_closes:
        print(f"[INFO] Loaded {len(recent_closes)} candles. Last close: {recent_closes[-1]:.2f}")
    else:
        print("[WARN] No candle data; waiting for websocket...")
    if mode == "live":
        balance = fetch_real_balance(api_key, secret, config.QUOTE_ASSET)
        print(f"[INFO] Real {config.QUOTE_ASSET} balance: {balance:.2f}")
    else:
        balance = config.PAPER_BALANCE
        print(f"[INFO] Paper balance: {balance:.2f} {config.QUOTE_ASSET}")
    print(f"[INFO] Bot running. Press Ctrl+C to stop.\n")
    while True:
        try:
            close_price = price_q.get(timeout=30)
        except queue.Empty:
            continue
        except Exception as e:
            print(f"[ERROR] Queue error: {e}", file=sys.stderr)
            continue
        recent_closes.append(close_price)
        if len(recent_closes) > 200:
            recent_closes.pop(0)
        if len(recent_closes) < config.MIN_CANDLES_FOR_SIGNAL:
            continue
        try:
            rsi = calc_rsi(recent_closes, period=14)
            macd, macd_signal, macd_hist = calc_macd(recent_closes, fast_period=12, slow_period=26, signal_period=9)
        except Exception as e:
            print(f"[WARN] Indicator error: {e}", file=sys.stderr)
            continue
        sma_val = calc_sma(recent_closes, config.TREND_SMA_PERIOD) if config.USE_TREND_FILTER else 0
        uptrend = is_uptrend(recent_closes, config.TREND_SMA_PERIOD, config.TREND_SLOPE_LOOKBACK) if config.USE_TREND_FILTER else True
        if config.LOG_STATUS_EVERY_TICK:
            ts_str = time.strftime("%H:%M:%S")
            pos_str = ""
            if position.in_position:
                pnl_pct = ((close_price - position.entry_price) / position.entry_price) * 100
                pos_str = (f" | POS: {position.qty:.6f} @ {position.entry_price:.2f}"
                           f" | SL: {position.stop_loss:.2f} | TP: {position.take_profit:.2f}"
                           f" | PnL: {pnl_pct:+.2f}%")
            sma_str = f" | SMA50: {sma_val:.2f}" if sma_val > 0 else ""
            trend_icon = "UP" if uptrend else "DN"
            print(f"[{ts_str}] {symbol} @ {close_price:.2f} | RSI: {rsi:.1f} | MACD: {macd:.2f} > {macd_signal:.2f}{sma_str} [{trend_icon}]{pos_str}")
        if position.in_position:
            position.update_trailing(close_price)
            exit_reason = position.check_exit(close_price, rsi)
            if exit_reason:
                reason_map = {"SL": "STOP-LOSS HIT", "TP": "TAKE-PROFIT HIT", "SIG": "RSI OVERBOUGHT SELL"}
                reason_str = reason_map.get(exit_reason, exit_reason)
                print(f"\n[EXIT] {reason_str} for {symbol}!")
                result = execute_trade(symbol, "SELL", position.qty, close_price, mode, api_key, secret, reason=reason_str)
                if result:
                    pnl = (result["price"] - position.entry_price) * position.qty - result["fee"]
                    pnl_pct = ((result["price"] - position.entry_price) / position.entry_price) * 100
                    print(f"  Realized PnL: {pnl:+.2f} USDT ({pnl_pct:+.2f}%)")
                    position.close()
                    last_trade_ts = int(time.time())
                    if mode == "paper":
                        balance += pnl
                continue
        if not position.in_position:
            now_ts = int(time.time())
            if now_ts - last_trade_ts < config.COOLDOWN_SECONDS:
                continue
            signal = evaluate_signal(recent_closes)
            if signal != "BUY":
                continue
            trend_note = " | Trend: SMA rising" if uptrend else ""
            print(f"\n[SIGNAL] BUY signal detected! RSI={rsi:.1f}{trend_note}")
            qty = calc_position_size(balance=balance, price=close_price, risk_pct=config.RISK_PER_TRADE, step_size=config.STEP_SIZE, min_notional=config.MIN_NOTIONAL)
            if qty <= 0:
                print("[WARN] Quantity too small; skipping.", file=sys.stderr)
                continue
            result = execute_trade(symbol, "BUY", qty, close_price, mode, api_key, secret, reason="RSI OVERSOLD")
            if result:
                position.open(result["price"], result["qty"], side="LONG")
                print(f"  Position opened: SL={position.stop_loss:.2f} | TP={position.take_profit:.2f}")
                if config.USE_TRAILING_STOP:
                    print(f"  Trailing stop active: {config.TRAILING_STOP_PCT*100:.1f}% from peak")
                last_trade_ts = int(time.time())


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python3 cli.py <symbol> <interval> <mode> [api_key] [secret]")
        print("  symbol   - e.g. BTCUSDT")
        print("  interval - e.g. 1m, 5m, 15m, 1h")
        print("  mode     - paper or live")
        print("  Keys loaded from .env if not passed as args")
        print("\nEdit config.py to adjust strategy, risk, stops, etc.")
        sys.exit(1)
    _, symbol, interval, mode = sys.argv[:4]
    api_key = sys.argv[4] if len(sys.argv) > 4 else os.environ.get("BINANCE_API_KEY", "")
    secret = sys.argv[5] if len(sys.argv) > 5 else os.environ.get("BINANCE_SECRET", "")
    if not all([symbol, interval, mode, api_key, secret]):
        print("[ERROR] Missing arguments or .env keys.", file=sys.stderr)
        sys.exit(1)
    if mode not in ("paper", "live"):
        print("Mode must be 'paper' or 'live'", file=sys.stderr)
        sys.exit(1)
    try:
        run_bot(symbol.upper(), interval, mode, api_key, secret)
    except KeyboardInterrupt:
        print("\n\n[INFO] Bot stopped by user. Goodbye!")
        sys.exit(0)
