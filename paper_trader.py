#!/usr/bin/env python3
import json
import sys
import os
import subprocess
from typing import Dict, Any

# Ensure the project root is on the import path for local modules
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ctx: codexhaven

def simulate_market_fill(symbol: str, side: str, quantity: float, depth_json: str) -> float:
    """
    Simulate a market order fill using a snapshot of the order book depth.

    Args:
        symbol: Trading pair symbol (e.g., "BTCUSDT").
        side: "BUY" or "SELL". BUY consumes asks, SELL consumes bids.
        quantity: Desired amount of base asset to trade.
        depth_json: JSON string containing order book depth with keys
                    "bids" and "asks". Each is a list of [price, volume] strings.

    Returns:
        Average execution price as a float. Returns 0.0 if the order cannot be filled.
    """
    if not isinstance(symbol, str):
        raise TypeError("symbol must be a string")
    if side.upper() not in ("BUY", "SELL"):
        raise ValueError("side must be 'BUY' or 'SELL'")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    try:
        orderbook = json.loads(depth_json)
    except json.JSONDecodeError as exc:
        raise ValueError("depth_json must be valid JSON") from exc

    # Determine which side of the book to consume
    levels = orderbook.get("asks" if side.upper() == "BUY" else "bids")
    if not isinstance(levels, list):
        raise ValueError("orderbook must contain 'bids' and 'asks' lists")

    filled = 0.0
    total_cost = 0.0

    for price_str, vol_str in levels:
        price = float(price_str)
        vol = float(vol_str)

        remaining = quantity - filled
        take = min(remaining, vol)
        total_cost += price * take
        filled += take

        if filled >= quantity:
            break

    if filled == 0:
        return 0.0
    return total_cost / filled


def apply_fees(amount: float, is_futures: bool) -> float:
    """
    Apply Binance fee to an amount.

    Args:
        amount: Gross amount (e.g., proceeds from a trade).
        is_futures: True for futures contracts, False for spot trading.

    Returns:
        Net amount after deducting the appropriate fee.
    """
    if amount < 0:
        raise ValueError("amount cannot be negative")
    fee_rate = 0.0002 if is_futures else 0.001  # 0.02% futures, 0.1% spot
    return amount * (1 - fee_rate)


def _fetch_order_book(symbol: str, limit: int = 100) -> Dict[str, Any]:
    """
    Helper to fetch a depth snapshot via Binance REST using the existing api_client.

    This function is internal to the paper trader and not part of the public API.
    """
    from api_client import curl_get  # Local import to avoid circular dependencies
    import time

    url = "https://api.binance.com/api/v3/depth"
    timestamp = int(time.time() * 1000)
    query = f"symbol={symbol}&limit={limit}"
    full_url = f"{url}?{query}"
    # Binance depth endpoint does not require signature, but we keep the pattern
    response = curl_get(full_url, os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_SECRET", ""), timestamp)
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        raise RuntimeError("Failed to parse order book JSON")


def simulate_trade(symbol: str, side: str, quantity: float, is_futures: bool = False) -> Dict[str, float]:
    """
    High‑level helper that fetches a depth snapshot, simulates the fill,
    applies fees, and returns detailed results.

    Returns:
        {
            "avg_price": float,
            "net_amount": float,   # after fees
            "gross_amount": float  # quantity * avg_price
        }
    """
    depth = _fetch_order_book(symbol)
    depth_json = json.dumps(depth)
    avg_price = simulate_market_fill(symbol, side, quantity, depth_json)
    if avg_price == 0.0:
        raise RuntimeError("Unable to fill the simulated order with current depth")
    gross = quantity * avg_price
    net = apply_fees(gross, is_futures)
    return {"avg_price": avg_price, "gross_amount": gross, "net_amount": net}