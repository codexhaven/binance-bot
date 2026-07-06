#!/usr/bin/env python3
import sys
import os
import math
import json
import time
import subprocess
from typing import Dict, Any, Optional

# Ensure the project root is on the import path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_client import curl_get, curl_post

# ctx: codexhaven

def calc_position_size(balance: float, price: float, risk_pct: float, step_size: float, min_notional: float) -> float:
    """
    Calculates the optimal position size based on account balance and risk percentage.
    Ensures the size adheres to the exchange's step size and minimum notional requirements.

    Args:
        balance: Current available balance in quote currency (e.g., USDT).
        price: Current market price of the asset.
        risk_pct: Percentage of balance to risk (e.g., 0.01 for 1%).
        step_size: The minimum quantity increment allowed by the exchange.
        min_notional: The minimum total order value allowed (qty * price).

    Returns:
        The calculated quantity as a float.
    """
    if price <= 0:
        return 0.0

    # Calculate raw size based on risk
    raw_size = (balance * risk_pct) / price
    
    # Floor to the nearest step size to avoid "precision" errors
    # Example: if step_size is 0.001, 1.23456 -> 1.234
    precision = abs(math.log10(step_size)) if step_size < 1 else 0
    size = math.floor(raw_size * (10**precision)) / (10**precision)
    
    # Ensure the order meets the minimum notional requirement
    if size * price < min_notional:
        # Calculate minimum quantity needed to meet notional
        min_qty = min_notional / price
        # Ceil to the nearest step size
        size = math.ceil(min_qty * (10**precision)) / (10**precision)
        
    return size

def fetch_mark_price(symbol: str, api_key: str, secret: str) -> float:
    """
    Fetches the current mark price for a symbol from the Binance Futures API.
    
    Args:
        symbol: Trading pair (e.g., 'BTCUSDT').
        api_key: Binance API Key.
        secret: Binance Secret Key.

    Returns:
        The mark price as a float.
    """
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    timestamp = int(time.time() * 1000)
    
    # Mark price endpoint is public, but we use the client wrapper for consistency
    # Note: curl_get handles the signature if required, though premiumIndex is public
    response_str = curl_get(url, api_key, secret, f"symbol={symbol}", timestamp)
    
    try:
        data = json.loads(response_str)
        return float(data['markPrice'])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        print(f"Error fetching mark price for {symbol}: {e}")
        return 0.0

def convert_dust(asset: str, api_key: str, secret: str) -> str:
    """
    Triggers the Binance 'Convert Small Balances to BNB' feature for a specific asset.
    
    Args:
        asset: The asset symbol to convert (e.g., 'ADA').
        api_key: Binance API Key.
        secret: Binance Secret Key.

    Returns:
        The raw JSON response from the API.
    """
    url = "https://api.binance.com/sapi/v1/asset/assetDustTransfer"
    timestamp = int(time.time() * 1000)
    payload = f"asset={asset}"
    
    return curl_post(url, api_key, secret, payload, timestamp)

def calculate_sl_tp(entry_price: float, side: str, sl_pct: float, tp_pct: float) -> Dict[str, float]:
    """
    Calculates Stop Loss and Take Profit price levels.

    Args:
        entry_price: The price at which the trade was entered.
        side: 'BUY' or 'SELL'.
        sl_pct: Stop loss percentage (e.g., 0.02 for 2%).
        tp_pct: Take profit percentage (e.g., 0.04 for 4%).

    Returns:
        A dictionary containing 'sl' and 'tp' prices.
    """
    if side.upper() == 'BUY':
        sl = entry_price * (1 - sl_pct)
        tp = entry_price * (1 + tp_pct)
    elif side.upper() == 'SELL':
        sl = entry_price * (1 + sl_pct)
        tp = entry_price * (1 - tp_pct)
    else:
        raise ValueError("Side must be either 'BUY' or 'SELL'")
        
    return {"sl": sl, "tp": tp}

if __name__ == "__main__":
    # Simple test suite for risk manager
    print("Testing Risk Manager...")
    
    # Test position sizing
    # Balance 1000, Price 50000, Risk 1%, Step 0.001, MinNotional 5
    size = calc_position_size(1000.0, 50000.0, 0.01, 0.001, 5.0)
    print(f"Calculated Size: {size} (Expected: 0.002)")
    
    # Test SL/TP
    levels = calculate_sl_tp(50000.0, 'BUY', 0.02, 0.05)
    print(f"SL/TP Levels: {levels}") # Expected SL: 49000, TP: 52500