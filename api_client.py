#!/usr/bin/env python3
import sys
import os
import subprocess
import hmac
import hashlib
import urllib.parse
import time
from typing import Dict, Any

# Ensure the project root is on the import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _sign(query_string: str, secret: str) -> str:
    """
    Create HMAC SHA256 signature for Binance API.

    Args:
        query_string: The URL‑encoded query string to sign.
        secret: Binance secret key.

    Returns:
        Hexadecimal signature string.
    """
    if not isinstance(query_string, str):
        raise TypeError("query_string must be a string")
    if not isinstance(secret, str):
        raise TypeError("secret must be a string")
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()


def _run_curl(command: list) -> str:
    """
    Execute a curl command and return stdout as a decoded string.

    Args:
        command: List of command arguments for subprocess.

    Returns:
        Decoded stdout from curl.

    Raises:
        RuntimeError: If curl exits with a non‑zero status.
    """
    if not isinstance(command, list) or not all(isinstance(c, str) for c in command):
        raise TypeError("command must be a list of strings")
    try:
        result = subprocess.check_output(command, stderr=subprocess.STDOUT)
        return result.decode().strip()
    except subprocess.CalledProcessError as exc:
        # Include curl's output for easier debugging
        raise RuntimeError(f"curl command failed: {exc.output.decode().strip()}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("curl executable not found on PATH") from exc


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
        Raw JSON response as a string.

    Raises:
        ValueError: If required arguments are missing or empty.
        RuntimeError: Propagated from _run_curl on failure.
    """
    if not base_url:
        raise ValueError("base_url must not be empty")
    if not api_key:
        raise ValueError("api_key must not be empty")
    if not secret:
        raise ValueError("secret must not be empty")
    if params is None:
        raise ValueError("params must be a dictionary, not None")

    if timestamp is None:
        timestamp = int(time.time() * 1000)

    # Add required timestamp
    query = dict(params)  # shallow copy to avoid mutating caller data
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
        Raw JSON response as a string.

    Raises:
        ValueError: If required arguments are missing or empty.
        RuntimeError: Propagated from _run_curl on failure.
    """
    if not base_url:
        raise ValueError("base_url must not be empty")
    if not api_key:
        raise ValueError("api_key must not be empty")
    if not secret:
        raise ValueError("secret must not be empty")
    if payload is None:
        raise ValueError("payload must be a dictionary, not None")

    if timestamp is None:
        timestamp = int(time.time() * 1000)

    # Add timestamp to query string for signature
    query = {"timestamp": str(timestamp)}
    query_string = urllib.parse.urlencode(query)
    signature = _sign(query_string, secret)

    # Build final URL with signature
    url = f"{base_url}?{query_string}&signature={signature}"

    # Encode payload for curl -d; handle empty payload gracefully
    data = urllib.parse.urlencode(payload) if payload else ""

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