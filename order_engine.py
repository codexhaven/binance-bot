#!/usr/bin/env python3
import os
import sys
import time
import json
from typing import Dict, Any

# Ensure the project root is on the import path for local modules
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from api_client import curl_post, curl_get, _sign, _run_curl

# ctx: codexhaven

def _format_quantity(quantity: float, step_size: float) -> str:
    """
    Adjust quantity to Binance step size.

    Args:
        quantity: Desired raw quantity.
        step_size: Minimum step size for the symbol.

    Returns:
        Quantity as a string formatted to the correct precision.
    """
    if step_size <= 0:
        raise ValueError("step_size must be positive")
    # Determine number of decimal places in step_size
    step_str = f"{step_size:.16f}".rstrip('0')
    if '.' in step_str:
        precision = len(step_str.split('.')[1])
    else:
        precision = 0
    adjusted = (int(quantity / step_size)) * step_size
    return f"{adjusted:.{precision}f}"


def _format_price(price: float, tick_size: float) -> str:
    """
    Adjust price to Binance tick size.

    Args:
        price: Desired raw price.
        tick_size: Minimum price increment.

    Returns:
        Price as a string formatted to the correct precision.
    """
    if tick_size <= 0:
        raise ValueError("tick_size must be positive")
    tick_str = f"{tick_size:.16f}".rstrip('0')
    if '.' in tick_str:
        precision = len(tick_str.split('.')[1])
    else:
        precision = 0
    adjusted = (int(price / tick_size)) * tick_size
    return f"{adjusted:.{precision}f}"


def place_market_order(symbol: str, side: str, quantity: float,
                       api_key: str, secret: str,
                       step_size: float = 0.000001) -> Dict[str, Any]:
    """
    Place a MARKET order on Binance Spot.

    Args:
        symbol: Trading pair (e.g., "BTCUSDT").
        side: "BUY" or "SELL".
        quantity: Desired order quantity.
        api_key: Binance API key.
        secret: Binance secret key.
        step_size: Symbol step size for quantity rounding.

    Returns:
        Parsed JSON response from Binance as a dict.
    """
    qty_str = _format_quantity(quantity, step_size)
    payload = f"symbol={symbol}&side={side.upper()}&type=MARKET&quantity={qty_str}"
    timestamp = int(time.time() * 1000)
    url = "https://api.binance.com/api/v3/order"
    response = curl_post(url, api_key, secret, payload, timestamp)
    return json.loads(response)


def place_limit_order(symbol: str, side: str, quantity: float, price: float,
                      api_key: str, secret: str,
                      step_size: float = 0.000001,
                      tick_size: float = 0.000001,
                      time_in_force: str = "GTC") -> Dict[str, Any]:
    """
    Place a LIMIT order on Binance Spot.

    Args:
        symbol: Trading pair.
        side: "BUY" or "SELL".
        quantity: Order quantity.
        price: Desired limit price.
        api_key: Binance API key.
        secret: Binance secret key.
        step_size: Quantity step size.
        tick_size: Price tick size.
        time_in_force: Order time in force (GTC, IOC, FOK).

    Returns:
        Parsed JSON response.
    """
    qty_str = _format_quantity(quantity, step_size)
    price_str = _format_price(price, tick_size)
    payload = (
        f"symbol={symbol}&side={side.upper()}&type=LIMIT&timeInForce={time_in_force}"
        f"&quantity={qty_str}&price={price_str}"
    )
    timestamp = int(time.time() * 1000)
    url = "https://api.binance.com/api/v3/order"
    response = curl_post(url, api_key, secret, payload, timestamp)
    return json.loads(response)


def place_oco_order(symbol: str, side: str, quantity: float,
                    price: float, stop_price: float,
                    api_key: str, secret: str,
                    step_size: float = 0.000001,
                    tick_size: float = 0.000001,
                    stop_limit_price: float = None,
                    stop_limit_time_in_force: str = "GTC") -> Dict[str, Any]:
    """
    Place an OCO (One‑Cancels‑Other) order on Binance Spot.

    Args:
        symbol: Trading pair.
        side: "BUY" or "SELL".
        quantity: Base order quantity.
        price: Limit price for the primary order.
        stop_price: Trigger price for the stop‑limit order.
        api_key: Binance API key.
        secret: Binance secret key.
        step_size: Quantity step size.
        tick_size: Price tick size.
        stop_limit_price: Optional explicit stop‑limit price; if None,
                          defaults to stop_price.
        stop_limit_time_in_force: Time in force for the stop‑limit leg.

    Returns:
        Parsed JSON response.
    """
    qty_str = _format_quantity(quantity, step_size)
    price_str = _format_price(price, tick_size)
    stop_price_str = _format_price(stop_price, tick_size)
    if stop_limit_price is None:
        stop_limit_price = stop_price
    stop_limit_price_str = _format_price(stop_limit_price, tick_size)

    payload = (
        f"symbol={symbol}&side={side.upper()}&type=OCO&quantity={qty_str}"
        f"&price={price_str}&stopPrice={stop_price_str}"
        f"&stopLimitPrice={stop_limit_price_str}"
        f"&stopLimitTimeInForce={stop_limit_time_in_force}"
    )
    timestamp = int(time.time() * 1000)
    url = "https://api.binance.com/api/v3/order/oco"
    response = curl_post(url, api_key, secret, payload, timestamp)
    return json.loads(response)


def place_stop_market_futures(symbol: str, side: str, quantity: float,
                              stop_price: float,
                              api_key: str, secret: str,
                              step_size: float = 0.000001) -> Dict[str, Any]:
    """
    Place a STOP_MARKET order on Binance Futures.

    Args:
        symbol: Futures symbol (e.g., "BTCUSDT").
        side: "BUY" or "SELL".
        quantity: Order quantity.
        stop_price: Trigger price for the stop market.
        api_key: Binance API key.
        secret: Binance secret key.
        step_size: Quantity step size.

    Returns:
        Parsed JSON response.
    """
    qty_str = _format_quantity(quantity, step_size)
    stop_price_str = f"{stop_price:.8f}"  # Futures typically allow 8‑dp precision
    payload = (
        f"symbol={symbol}&side={side.upper()}&type=STOP_MARKET"
        f"&quantity={qty_str}&stopPrice={stop_price_str}"
    )
    timestamp = int(time.time() * 1000)
    url = "https://fapi.binance.com/fapi/v1/order"
    response = curl_post(url, api_key, secret, payload, timestamp)
    return json.loads(response)


def get_exchange_info(api_key: str, secret: str) -> Dict[str, Any]:
    """
    Retrieve Binance exchange information (rate limits, symbol filters, etc.).

    Args:
        api_key: Binance API key.
        secret: Binance secret key.

    Returns:
        Parsed JSON dictionary containing exchange info.
    """
    timestamp = int(time.time() * 1000)
    url = "https://api.binance.com/api/v3/exchangeInfo"
    response = curl_get(url, api_key, secret, timestamp)
    return json.loads(response)


def get_symbol_filters(symbol: str, api_key: str, secret: str) -> Dict[str, Any]:
    """
    Extract filter information (stepSize, tickSize, minNotional, etc.) for a
    specific trading pair.

    Args:
        symbol: Trading pair.
        api_key: Binance API key.
        secret: Binance secret key.

    Returns:
        Dictionary of filter parameters for the symbol.
    """
    info = get_exchange_info(api_key, secret)
    for s in info.get("symbols", []):
        if s.get("symbol") == symbol.upper():
            filters = {f["filterType"]: f for f in s.get("filters", [])}
            return filters
    raise ValueError(f"Symbol {symbol} not found in exchange info")


if __name__ == "__main__":
    # Simple manual test harness
    if len(sys.argv) < 6:
        print("Usage: order_engine.py <symbol> <side> <qty> <price|stop> <mode>")
        sys.exit(1)

    mode = sys.argv[5].lower()
    api_key = os.getenv("BINANCE_API_KEY")
    secret = os.getenv("BINANCE_API_SECRET")
    if not api_key or not secret:
        print("Set BINANCE_API_KEY and BINANCE_API_SECRET environment variables.")
        sys.exit(1)

    symbol = sys.argv[1]
    side = sys.argv[2]
    qty = float(sys.argv[3])

    if mode == "market":
        res = place_market_order(symbol, side, qty, api_key, secret)
    elif mode == "limit":
        price = float(sys.argv[4])
        res = place_limit_order(symbol, side, qty, price, api_key, secret)
    elif mode == "oco":
        price = float(sys.argv[4])
        stop_price = float(sys.argv[5])
        res = place_oco_order(symbol, side, qty, price, stop_price,
                              api_key, secret)
    elif mode == "stop_market_futures":
        stop_price = float(sys.argv[4])
        res = place_stop_market_futures(symbol, side, qty, stop_price,
                                        api_key, secret)
    else:
        print(f"Unsupported mode: {mode}")
        sys.exit(1)

    print(json.dumps(res, indent=2))