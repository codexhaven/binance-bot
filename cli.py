#!/usr/bin/env python3
import sys
import os
import json
import time
import threading
import queue
from typing import List

# Ensure project root is on import path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from kline_stream import start_kline_ws, fetch_latest_kline
from indicator import calc_rsi, calc_macd
from risk_manager import calc_position_size, fetch_mark_price
from order_engine import place_market_order, place_oco_order, place_stop_market_futures
from paper_trader import simulate_market_fill, apply_fees
from trade_logger import init_db, log_trade, get_last_trade, export_csv


def _fetch_recent_closes(symbol: str, interval: str, api_key: str, secret: str,
                         count: int = 100) -> List[float]:
    """
    Retrieve the most recent ``count`` closing prices via the Binance klines REST endpoint.

    Parameters
    ----------
    symbol : str
        Trading pair, e.g. ``BTCUSDT``.
    interval : str
        Binance kline interval, e.g. ``1m``.
    api_key : str
        Binance API key.
    secret : str
        Binance secret.
    count : int, optional
        Number of closing prices to return (default 100).

    Returns
    -------
    List[float]
        List of closing prices ordered from oldest to newest. Returns an empty list on error.
    """
    if not symbol or not interval:
        print("[ERROR] Symbol or interval is empty.", file=sys.stderr)
        return []

    raw = fetch_latest_kline(symbol, interval, api_key, secret)
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("code"):
            raise RuntimeError(f"Binance error: {data.get('msg')}")
        # Binance returns a list of lists; each inner list: [open_time, o, h, l, c, v, ...]
        closes = [float(k[4]) for k in data[-count:]]
        return closes
    except Exception as e:
        print(f"[ERROR] Failed to parse klines: {e}", file=sys.stderr)
        return []


def _candle_callback_factory(price_queue: queue.Queue):
    """
    Create a callback that puts the candle close price into the provided queue.

    Parameters
    ----------
    price_queue : queue.Queue
        Queue used to communicate candle close prices between the websocket thread and the main loop.

    Returns
    -------
    function
        Callback compatible with ``start_kline_ws`` that receives candle data.
    """
    def candle_cb(open_time, o, h, l, c, v):
        try:
            price_queue.put_nowait(float(c))
        except queue.Full:
            # If the queue is full we simply drop the price; the main loop will use the most recent value.
            pass
    return candle_cb


def run_bot(symbol: str, interval: str, mode: str, api_key: str, secret: str) -> None:
    """
    Main bot loop.

    Parameters
    ----------
    symbol : str
        Trading pair, e.g. ``BTCUSDT``.
    interval : str
        Binance kline interval, e.g. ``1m``.
    mode : str
        ``paper`` for simulation or ``live`` for real orders.
    api_key : str
        Binance API key.
    secret : str
        Binance secret.
    """
    if mode not in ("paper", "live"):
        print("[ERROR] Invalid mode; must be 'paper' or 'live'.", file=sys.stderr)
        return

    # Initialise SQLite trade log
    try:
        init_db()
    except Exception as e:
        print(f"[ERROR] Failed to initialise trade log database: {e}", file=sys.stderr)
        return

    price_q: queue.Queue = queue.Queue(maxsize=10)

    # Start websocket thread
    candle_cb = _candle_callback_factory(price_q)
    try:
        threading.Thread(target=start_kline_ws,
                         args=(symbol, interval, 'candle_cb'),
                         daemon=True).start()
    except Exception as e:
        print(f"[ERROR] Failed to start kline websocket: {e}", file=sys.stderr)
        return

    # Warm‑up: fetch recent closes for indicator calculations
    recent_closes = _fetch_recent_closes(symbol, interval, api_key, secret, count=200)
    if not recent_closes:
        print("[WARN] No recent close data available; bot will continue but indicators may be inaccurate.", file=sys.stderr)

    while True:
        try:
            close_price = price_q.get(timeout=30)
        except queue.Empty:
            # No new candle – continue waiting
            continue
        except Exception as e:
            print(f"[ERROR] Unexpected error retrieving price from queue: {e}", file=sys.stderr)
            continue

        # Update rolling close list
        recent_closes.append(close_price)
        if len(recent_closes) > 200:
            recent_closes.pop(0)

        # Indicator calculations
        try:
            rsi = calc_rsi(recent_closes, period=14)
            macd, macd_signal, _ = calc_macd(recent_closes, fast=12, slow=26, signal=9)
        except Exception as e:
            print(f"[WARN] Indicator error: {e}", file=sys.stderr)
            continue

        # Simple strategy: RSI <30 → BUY, RSI >70 → SELL
        side = None
        if rsi < 30:
            side = "BUY"
        elif rsi > 70:
            side = "SELL"

        if side is None:
            continue  # No signal

        # Determine position size
        try:
            # For futures we could fetch mark price; for spot use close_price
            price_for_size = close_price
            # Placeholder balance – in a production bot replace with real account balance query
            balance = 10000.0
            qty = calc_position_size(
                balance=balance,
                price=price_for_size,
                risk_pct=0.01,
                step_size=0.00001,
                min_notional=5.0,
            )
            if qty <= 0:
                print("[WARN] Calculated quantity is zero; skipping order.", file=sys.stderr)
                continue
        except Exception as e:
            print(f"[ERROR] Position size calculation failed: {e}", file=sys.stderr)
            continue

        timestamp = int(time.time() * 1000)

        if mode == "paper":
            # Simulate fill using a dummy depth snapshot (empty for brevity)
            depth_snapshot = json.dumps({"bids": [], "asks": []})
            try:
                fill_price = simulate_market_fill(symbol, side, qty, depth_snapshot)
                net_price = apply_fees(fill_price * qty, is_futures=False) / qty
                fee = fill_price * qty - net_price * qty
            except Exception as e:
                print(f"[ERROR] Paper trade simulation failed: {e}", file=sys.stderr)
                continue

            try:
                log_trade(
                    ts=timestamp,
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    price=net_price,
                    fee=fee,
                    fee_asset="USDT",
                    realized_pnl=0.0,
                    mode="paper",
                    order_id="simulated",
                )
            except Exception as e:
                print(f"[ERROR] Failed to log paper trade: {e}", file=sys.stderr)

            print(f"[PAPER] {side} {qty:.6f} {symbol} @ {net_price:.2f}")
        else:
            # Live mode – place market order
            try:
                resp = place_market_order(symbol, side, qty, api_key, secret)
                resp_json = json.loads(resp)
                order_id = resp_json.get("orderId", "unknown")
                fills = resp_json.get("fills", [])
                if fills:
                    total_qty = sum(float(f["qty"]) for f in fills)
                    avg_price = sum(float(f["price"]) * float(f["qty"]) for f in fills) / total_qty if total_qty else close_price
                else:
                    avg_price = close_price
                fee = sum(float(f.get("commission", 0)) for f in fills)
                log_trade(
                    ts=timestamp,
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    price=avg_price,
                    fee=fee,
                    fee_asset="USDT",
                    realized_pnl=0.0,
                    mode="live",
                    order_id=str(order_id),
                )
                print(f"[LIVE] {side} {qty:.6f} {symbol} @ {avg_price:.2f} (order {order_id})")
            except Exception as e:
                print(f"[ERROR] Live order failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print("Usage: python3 cli.py <symbol> <interval> <mode> <api_key> <secret>")
        sys.exit(1)

    _, symbol, interval, mode, api_key, secret = sys.argv

    if not all([symbol, interval, mode, api_key, secret]):
        print("[ERROR] All arguments must be non‑empty.", file=sys.stderr)
        sys.exit(1)

    if mode not in ("paper", "live"):
        print("Mode must be 'paper' or 'live'", file=sys.stderr)
        sys.exit(1)

    run_bot(symbol.upper(), interval, mode, api_key, secret)