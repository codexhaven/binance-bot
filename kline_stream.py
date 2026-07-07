#!/usr/bin/env python3
"""
Kline streamer using REST API polling (no websocat needed).
Falls back gracefully and works everywhere with just curl.
"""
import os
import sys
import subprocess
import json
import time
import threading
from typing import Callable, List, Tuple

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def start_kline_ws(symbol: str, interval: str, callback: Callable) -> None:
    """
    Poll Binance REST API for new candles.
    Calls callback(open_time, o, h, l, c, v, is_closed) when a new candle closes.
    """
    ws_url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval={interval}&limit=2"

    def _poller():
        last_open_time = 0
        # Parse interval to seconds for polling frequency
        interval_seconds = _parse_interval_to_seconds(interval)
        poll_every = max(30, interval_seconds // 10)  # Poll every 1/10th of interval, min 30s

        print(f"[kline_ws] REST polling {symbol} {interval} every {poll_every}s", file=sys.stderr)

        while True:
            try:
                raw = subprocess.run(
                    ["curl", "-s", "--max-time", "10", ws_url],
                    capture_output=True, text=True, timeout=15
                ).stdout
                data = json.loads(raw)

                if isinstance(data, dict) and data.get("code"):
                    print(f"[kline_ws] API error: {data.get('msg')}", file=sys.stderr)
                    time.sleep(poll_every)
                    continue

                if not isinstance(data, list) or len(data) < 1:
                    time.sleep(poll_every)
                    continue

                # data[-1] = current forming candle, data[-2] = last closed candle
                # Check the most recent CLOSED candle
                for kline in data:
                    open_time = int(kline[0])
                    o = float(kline[1])
                    h = float(kline[2])
                    l = float(kline[3])
                    c = float(kline[4])
                    v = float(kline[5])
                    is_closed = True  # We only process closed candles from REST

                    # Only fire callback for NEW closed candles we haven't seen
                    if open_time > last_open_time:
                        last_open_time = open_time
                        callback(open_time, o, h, l, c, v, is_closed)

            except subprocess.TimeoutExpired:
                print(f"[kline_ws] curl timeout, retrying...", file=sys.stderr)
            except json.JSONDecodeError as e:
                print(f"[kline_ws] JSON parse error: {e}", file=sys.stderr)
            except Exception as e:
                print(f"[kline_ws] Polling error: {e}", file=sys.stderr)

            time.sleep(poll_every)

    thread = threading.Thread(target=_poller, daemon=True)
    thread.start()


def _parse_interval_to_seconds(interval: str) -> int:
    """Parse Binance interval string to seconds."""
    try:
        num = int(interval[:-1])
        unit = interval[-1].lower()
        if unit == 's':
            return num
        elif unit == 'm':
            return num * 60
        elif unit == 'h':
            return num * 3600
        elif unit == 'd':
            return num * 86400
    except (ValueError, IndexError):
        pass
    return 900  # Default 15 minutes


def fetch_latest_kline(symbol: str, interval: str,
                       api_key: str, secret: str) -> Tuple[int, float, float, float, float, float, bool]:
    """Retrieve the most recent kline via Binance REST API."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval={interval}&limit=1"
    response = subprocess.run(["curl", "-s", url], capture_output=True, text=True).stdout
    data = json.loads(response)
    if not isinstance(data, list) or not data:
        raise ValueError("Empty kline data")
    kline = data[0]
    return (int(kline[0]), float(kline[1]), float(kline[2]),
            float(kline[3]), float(kline[4]), float(kline[5]), True)


def reconcile_initial_candle(symbol: str, interval: str,
                            api_key: str, secret: str,
                            ws_callback: Callable) -> None:
    try:
        open_time, o, h, l, c, v, is_closed = fetch_latest_kline(symbol, interval, api_key, secret)
        ws_callback(open_time, o, h, l, c, v, is_closed)
    except Exception as exc:
        sys.stderr.write(f"[kline_reconcile] Unable to fetch initial candle: {exc}\n")


def start_stream_with_reconciliation(symbol: str, interval: str,
                                     api_key: str, secret: str,
                                     callback: Callable) -> None:
    reconcile_initial_candle(symbol, interval, api_key, secret, callback)
    start_kline_ws(symbol, interval, callback)
