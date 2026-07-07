#!/usr/bin/env python3
"""
Binance Trading Bot - Enhanced Edition v4
=========================================
Strategy: Buy oversold dips in uptrends (SMA rising)
Only evaluates on candle CLOSE (not every tick).
"""
import sys
import os
import json
import time
import threading
import queue
import subprocess
import sqlite3
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
from ai_predictor import AIPredictor, extract_features as ai_extract_features


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

def fetch_recent_candles(symbol: str, interval: str, count: int = 250) -> List[Dict]:
    """Fetch full OHLCV candle history for AI feature extraction."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval={interval}&limit={count}"
    try:
        raw = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=15).stdout
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("code"):
            print(f"[ERROR] Binance klines error: {data.get('msg')}", file=sys.stderr)
            return []
        candles = []
        for k in data:
            candles.append({
                "open_time": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            })
        return candles
    except Exception as e:
        print(f"[ERROR] Failed to fetch candles: {e}", file=sys.stderr)
        return []


# Global AI predictor cache
ai_predictors: Dict[str, AIPredictor] = {}

def get_ai_predictor(symbol: str) -> AIPredictor:
    """Load AI model for symbol (cached)"""
    if symbol not in ai_predictors:
        ai_predictors[symbol] = AIPredictor(symbol)
    return ai_predictors[symbol]

def evaluate_signal_ai(candles: list, symbol: str) -> tuple:
    """AI-powered entry signal. Returns (signal, confidence)"""
    if len(candles) < 200:
        return None, 0.0
    ai = get_ai_predictor(symbol)
    if not ai.trees:
        return None, 0.0
    should_buy, proba = ai.predict(candles)
    if should_buy:
        return "BUY", proba
    return None, proba


def candle_callback_factory(price_queue: queue.Queue):
    """
    Only process CLOSED candles.
    kline_stream calls: callback(open_time, o, h, l, c, v, is_closed)
    """
    def candle_cb(*args):
        try:
            candle = None
            is_closed = False

            if len(args) >= 7:
                # Format from kline_stream: (open_time, o, h, l, c, v, is_closed)
                candle = {
                    "open_time": int(args[0]),
                    "open": float(args[1]),
                    "high": float(args[2]),
                    "low": float(args[3]),
                    "close": float(args[4]),
                    "volume": float(args[5]),
                }
                is_closed = bool(args[6])
            elif len(args) >= 5:
                candle = {
                    "open_time": int(args[0]),
                    "open": float(args[1]),
                    "high": float(args[2]),
                    "low": float(args[3]),
                    "close": float(args[4]),
                    "volume": float(args[5]) if len(args) > 5 else 0,
                }
                is_closed = True
            elif len(args) == 1:
                cd = args[0]
                if isinstance(cd, dict):
                    k = cd.get("k", cd)
                    if isinstance(k, dict):
                        candle = {
                            "open_time": int(k.get("t", k.get("open_time", 0))),
                            "open": float(k.get("o", k.get("open", 0))),
                            "high": float(k.get("h", k.get("high", 0))),
                            "low": float(k.get("l", k.get("low", 0))),
                            "close": float(k.get("c", k.get("close", 0))),
                            "volume": float(k.get("v", k.get("volume", 0))),
                        }
                        is_closed = bool(k.get("x", k.get("isClosed", False)))
                    else:
                        candle = {
                            "open_time": int(cd.get("t", cd.get("open_time", 0))),
                            "open": float(cd.get("o", cd.get("open", 0))),
                            "high": float(cd.get("h", cd.get("high", 0))),
                            "low": float(cd.get("l", cd.get("low", 0))),
                            "close": float(cd.get("c", cd.get("close", 0))),
                            "volume": float(cd.get("v", cd.get("volume", 0))),
                        }
                        is_closed = bool(cd.get("x", cd.get("isClosed", False)))
                elif isinstance(cd, (list, tuple)):
                    candle = {
                        "open_time": int(cd[0]) if len(cd) > 0 else 0,
                        "open": float(cd[1]) if len(cd) > 1 else 0,
                        "high": float(cd[2]) if len(cd) > 2 else 0,
                        "low": float(cd[3]) if len(cd) > 3 else 0,
                        "close": float(cd[4]) if len(cd) > 4 else 0,
                        "volume": float(cd[5]) if len(cd) > 5 else 0,
                    }
                    is_closed = True
                else:
                    return
            else:
                return

            # CRITICAL: Only queue when candle is actually closed
            if is_closed and candle and candle["close"] > 0:
                price_queue.put_nowait(candle)
        except queue.Full:
            pass
        except Exception:
            pass
    return candle_cb


def execute_trade(
    symbol: str, side: str, qty: float, price: float,
    mode: str, api_key: str, secret: str, reason: str = "SIGNAL",
    realized_pnl: float = 0.0,
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
            fee=fee, fee_asset="USDT", realized_pnl=realized_pnl, mode=mode, order_id=order_id,
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
    print(f"  Strategy: AI Random Forest (150 trees, 20 features){trend_str}")
    print(f"  Risk: {config.RISK_PER_TRADE*100:.1f}%/trade  |  SL: {config.STOP_LOSS_PCT*100:.1f}%  |  TP: {config.TAKE_PROFIT_PCT*100:.1f}%")
    if config.USE_TRAILING_STOP:
        print(f"  Trailing stop: {config.TRAILING_STOP_PCT*100:.1f}% from peak")
    print(f"  Cooldown: {config.COOLDOWN_SECONDS}s  |  Max positions: {config.MAX_POSITIONS}")
    print(f"  Signal eval: ON CANDLE CLOSE only")
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
    print(f"\n[INFO] Fetching {symbol} candle history (250 candles for AI)...")
    recent_candles = fetch_recent_candles(symbol, interval, count=250)
    recent_closes = [c["close"] for c in recent_candles]
    if recent_candles:
        print(f"[INFO] Loaded {len(recent_candles)} candles. Last close: {recent_candles[-1]['close']:.2f}")
        # Pre-load AI model
        ai = get_ai_predictor(symbol)
        if ai.trees:
            # Quick test prediction on current data
            _, test_proba = ai.predict(recent_candles)
            print(f"[INFO] AI model ready. Current confidence: {test_proba*100:.1f}% (threshold: {ai.threshold*100:.0f}%)")
    else:
        print("[WARN] No candle data; waiting for websocket...")
        recent_candles = []
    if mode == "live":
        balance = fetch_real_balance(api_key, secret, config.QUOTE_ASSET)
        print(f"[INFO] Real {config.QUOTE_ASSET} balance: {balance:.2f}")
    else:
        balance = config.PAPER_BALANCE
        print(f"[INFO] Paper balance: {balance:.2f} {config.QUOTE_ASSET}")
    print(f"[INFO] Bot running. Evaluates on {interval} candle close. Press Ctrl+C to stop.\n")
    while True:
        try:
            candle_data = price_q.get(timeout=60)
            close_price = candle_data["close"] if isinstance(candle_data, dict) else candle_data
        except queue.Empty:
            # Heartbeat: show we're alive and waiting
            mins_to_close = 15 - (int(time.time()) // 60 % 15)
            ai_pct = 0.0
            if recent_candles and len(recent_candles) >= 200:
                try:
                    _, ai_pct = evaluate_signal_ai(recent_candles, symbol)
                except:
                    pass
            last_price = recent_closes[-1] if recent_closes else 0
            print(f"[{time.strftime('%H:%M:%S')}] Waiting for next candle close ({mins_to_close}m) | {symbol} @ {last_price:.2f} | AI: {ai_pct*100:.1f}%", end="\r", flush=True)
            continue
        except Exception as e:
            print(f"[ERROR] Queue error: {e}", file=sys.stderr)
            continue
        recent_closes.append(close_price)
        if isinstance(candle_data, dict):
            recent_candles.append(candle_data)
            if len(recent_candles) > 300:
                recent_candles.pop(0)
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
            ai_conf = 0.0
            if len(recent_candles) >= 200:
                _, ai_conf = evaluate_signal_ai(recent_candles, symbol)
            print(f"[{ts_str}] {symbol} @ {close_price:.2f} | RSI: {rsi:.1f} | MACD: {macd:.2f} > {macd_signal:.2f}{sma_str} [{trend_icon}] | AI: {ai_conf*100:.0f}%{pos_str}")
        # ---- EXIT LOGIC ----
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
                    try:
                        conn = sqlite3.connect(config.DB_PATH)
                        conn.execute("UPDATE trades SET realized_pnl=? WHERE order_id=? AND side='SELL'",
                                     (pnl, result["order_id"]))
                        conn.commit()
                        conn.close()
                    except Exception:
                        pass
                    position.close()
                    last_trade_ts = int(time.time())
                    if mode == "paper":
                        balance += pnl
                continue
        # ---- ENTRY LOGIC ----
        if not position.in_position:
            now_ts = int(time.time())
            if now_ts - last_trade_ts < config.COOLDOWN_SECONDS:
                continue
            signal, ai_proba = evaluate_signal_ai(recent_candles, symbol)
            if signal != "BUY":
                continue
            trend_note = " | Trend: SMA rising" if uptrend else ""
            print(f"\n[SIGNAL] AI BUY signal detected! Confidence={ai_proba*100:.1f}%{trend_note}")
            qty = calc_position_size(balance=balance, price=close_price, risk_pct=config.RISK_PER_TRADE, step_size=config.STEP_SIZE, min_notional=config.MIN_NOTIONAL)
            if qty <= 0:
                print("[WARN] Quantity too small; skipping.", file=sys.stderr)
                continue
            result = execute_trade(symbol, "BUY", qty, close_price, mode, api_key, secret, reason="AI SIGNAL")
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
