#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import time
import threading
from typing import Callable, List, Tuple

# Ensure the project root is on the import path for local modules
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from api_client import curl_get  # noqa: E402

def _run_websocat(command: List[str]) -> subprocess.Popen:
    """
    Launch websocat with the given command list and return the Popen object.
    The stdout is piped line‑by‑line for processing.

    Args:
        command: List of command arguments for websocat.

    Returns:
        subprocess.Popen instance with stdout and stderr piped.

    Raises:
        TypeError: If command is not a list of strings.
        RuntimeError: If the subprocess cannot be started.
    """
    if not isinstance(command, list) or not all(isinstance(c, str) for c in command):
        raise TypeError("command must be a list of strings")
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
        return proc
    except Exception as exc:
        raise RuntimeError(f"Failed to start websocat: {exc}") from exc


def start_kline_ws(symbol: str, interval: str,
                   callback: Callable[[int, float, float, float, float, float], None]) -> None:
    """
    Open a Binance kline WebSocket stream for the given symbol and interval.
    For each incoming candle, the callback is invoked with:
        (open_time, open, high, low, close, volume)

    Args:
        symbol: Trading pair in lowercase (e.g., "btcusdt").
        interval: Binance interval string (e.g., "1m", "5m").
        callback: Function to handle parsed candle data.

    Raises:
        TypeError: If inputs are of incorrect type.
        RuntimeError: If websocat cannot be started.
    """
    if not isinstance(symbol, str) or not isinstance(interval, str):
        raise TypeError("symbol and interval must be strings")
    if not callable(callback):
        raise TypeError("callback must be callable")

    ws_url = f"wss://stream.binance.com:9443/ws/{symbol}@kline_{interval}"
    proc = _run_websocat(["websocat", "-t", ws_url])

    def _reader():
        """
        Reads lines from websocat stdout, parses JSON, and forwards candle data.
        """
        assert proc.stdout is not None  # for type checkers
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                k = data.get("k", {})
                open_time = int(k.get("t", 0))
                o = float(k.get("o", 0))
                h = float(k.get("h", 0))
                l = float(k.get("l", 0))
                c = float(k.get("c", 0))
                v = float(k.get("v", 0))
                callback(open_time, o, h, l, c, v)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                sys.stderr.write(f"[kline_ws] Failed to parse line: {exc}\n")
                continue
        # If the loop exits, the subprocess likely terminated
        sys.stderr.write("[kline_ws] WebSocket reader stopped.\n")

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()


def fetch_latest_kline(symbol: str, interval: str,
                       api_key: str, secret: str) -> Tuple[int, float, float, float, float, float]:
    """
    Retrieve the most recent completed kline via Binance REST API.

    Returns a tuple:
        (open_time, open, high, low, close, volume)

    Raises:
        TypeError: If any argument is not a string.
        RuntimeError: If the REST request fails or returns unexpected data.
    """
    if not all(isinstance(v, str) for v in (symbol, interval, api_key, secret)):
        raise TypeError("symbol, interval, api_key, and secret must be strings")

    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol.upper()}&interval={interval}&limit=1"
    url = "https://api.binance.com/api/v3/klines"
    response = curl_get(url, api_key, secret, f"{query}&timestamp={timestamp}")
    try:
        data = json.loads(response)
        if not isinstance(data, list) or not data:
            raise ValueError("Empty kline data")
        kline = data[0]
        open_time = int(kline[0])
        o = float(kline[1])
        h = float(kline[2])
        l = float(kline[3])
        c = float(kline[4])
        v = float(kline[5])
        return open_time, o, h, l, c, v
    except (json.JSONDecodeError, IndexError, ValueError, TypeError) as exc:
        raise RuntimeError(f"Failed to fetch latest kline: {exc}") from exc


def reconcile_initial_candle(symbol: str, interval: str,
                            api_key: str, secret: str,
                            ws_callback: Callable[[int, float, float, float, float, float], None]) -> None:
    """
    When starting the WS, the first candle may be incomplete. This helper fetches
    the latest completed candle via REST and feeds it to the same callback before
    the WS begins emitting new candles.

    Args:
        symbol: Trading pair (e.g., "btcusdt").
        interval: Binance interval string.
        api_key: Binance API key.
        secret: Binance secret key.
        ws_callback: Same callback used for WS processing.
    """
    try:
        open_time, o, h, l, c, v = fetch_latest_kline(symbol, interval, api_key, secret)
        ws_callback(open_time, o, h, l, c, v)
    except Exception as exc:
        sys.stderr.write(f"[kline_reconcile] Unable to fetch initial candle: {exc}\n")


def start_stream_with_reconciliation(symbol: str, interval: str,
                                     api_key: str, secret: str,
                                     callback: Callable[[int, float, float, float, float, float], None]) -> None:
    """
    Convenience wrapper that first reconciles the latest completed candle via REST
    and then starts the live WebSocket stream.

    This ensures the strategy always has a full candle to work with before the
    first real‑time update arrives.

    Args:
        symbol: Trading pair in lowercase.
        interval: Binance interval string.
        api_key: Binance API key.
        secret: Binance secret key.
        callback: Function to handle candle data.
    """
    reconcile_initial_candle(symbol, interval, api_key, secret, callback)
    start_kline_ws(symbol, interval, callback)