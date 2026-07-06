#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import subprocess
import hmac
import hashlib
import urllib.parse
import time
from typing import Dict

# ctx: codexhaven

def _sign(query_string: str, secret: str) -> str:
    """Create HMAC SHA256 signature for Binance API."""
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()


def _run_curl(command: list) -> str:
    """Execute a curl command and return stdout as string."""
    result = subprocess.check_output(command, stderr=subprocess.STDOUT)
    return result.decode().strip()


def curl_get(
    base_url: str,
    api_key: str,
    secret: str,
    params: Dict[str, str],
    timestamp: int | None = None,
) -> str:
    """
    Perform a signed GET request to Binance REST API using curl.

    Args:
        base_url: Full endpoint URL (e.g., "https://api.binance.com/api/v3/account").
        api_key: Binance API key.
        secret: Binance secret key.
        params: Dictionary of query parameters (excluding timestamp & signature).
        timestamp: Optional epoch ms; if None, current time is used.

    Returns:
        Raw JSON response as string.
    """
    if timestamp is None:
        timestamp = int(time.time() * 1000)

    # Add required timestamp
    query = dict(params)
    query["timestamp"] = str(timestamp)

    # Build query string for signature
    query_string = urllib.parse.urlencode(query)
    signature = _sign(query_string, secret)

    # Append signature
    full_query = f"{query_string}&signature={signature}"
    url = f"{base_url}?{full_query}"

    cmd = [
        "curl",
        "-s",
        "-H",
        f"X-MBX-APIKEY: {api_key}",
        url,
    ]
    return _run_curl(cmd)


def curl_post(
    base_url: str,
    api_key: str,
    secret: str,
    payload: Dict[str, str],
    timestamp: int | None = None,
) -> str:
    """
    Perform a signed POST request to Binance REST API using curl.

    Args:
        base_url: Full endpoint URL (e.g., "https://api.binance.com/api/v3/order").
        api_key: Binance API key.
        secret: Binance secret key.
        payload: Dictionary of form‑urlencoded body parameters (excluding timestamp & signature).
        timestamp: Optional epoch ms; if None, current time is used.

    Returns:
        Raw JSON response as string.
    """
    if timestamp is None:
        timestamp = int(time.time() * 1000)

    # Add timestamp to query string for signature
    query = {"timestamp": str(timestamp)}
    query_string = urllib.parse.urlencode(query)
    signature = _sign(query_string, secret)

    # Build final URL with signature
    url = f"{base_url}?{query_string}&signature={signature}"

    # Encode payload for curl -d
    data = urllib.parse.urlencode(payload)

    cmd = [
        "curl",
        "-s",
        "-X",
        "POST",
        "-H",
        "Content-Type: application/x-www-form-urlencoded",
        "-H",
        f"X-MBX-APIKEY: {api_key}",
        url,
        "-d",
        data,
    ]
    return _run_curl(cmd)