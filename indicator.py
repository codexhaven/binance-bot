#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import math
from typing import List, Tuple

# ctx: codexhaven

def _average_gain_loss(changes: List[float]) -> Tuple[float, float]:
    """Helper to compute average gain and loss from a list of price changes."""
    gains = [c for c in changes if c > 0]
    losses = [-c for c in changes if c < 0]
    avg_gain = sum(gains) / len(changes) if changes else 0.0
    avg_loss = sum(losses) / len(changes) if changes else 0.0
    return avg_gain, avg_loss


def calc_rsi(closes: List[float], period: int = 14) -> float:
    """
    Calculate the Relative Strength Index (RSI) for a series of closing prices.

    Args:
        closes: List of closing prices ordered from oldest to newest.
        period: Look‑back period for RSI calculation (default 14).

    Returns:
        RSI value as a float between 0 and 100.

    Raises:
        ValueError: If not enough closing prices are provided.
    """
    if period <= 0:
        raise ValueError("period must be a positive integer")
    if len(closes) < period + 1:
        raise ValueError(f"At least {period + 1} closing prices are required")

    # Compute price changes
    changes = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]

    # Initial average gain/loss
    initial_changes = changes[-period:]
    avg_gain, avg_loss = _average_gain_loss(initial_changes)

    # Smoothed RSI using Wilder's method
    for change in changes[-(len(changes) - period):]:
        gain = max(change, 0)
        loss = -min(change, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def _ema(values: List[float], period: int) -> List[float]:
    """
    Compute Exponential Moving Average (EMA) for a list of values.

    Args:
        values: List of numeric values.
        period: EMA period.

    Returns:
        List of EMA values, same length as input (first EMA starts at index period-1).
    """
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        raise ValueError("Not enough data points for EMA calculation")

    k = 2 / (period + 1)
    ema_vals: List[float] = []
    # Simple Moving Average for first EMA seed
    sma = sum(values[:period]) / period
    ema_vals.append(sma)
    for price in values[period:]:
        ema_next = price * k + ema_vals[-1] * (1 - k)
        ema_vals.append(ema_next)
    return ema_vals


def calc_macd(
    closes: List[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> Tuple[float, float, float]:
    """
    Calculate MACD line, Signal line, and Histogram.

    Args:
        closes: List of closing prices ordered from oldest to newest.
        fast_period: Period for the fast EMA (default 12).
        slow_period: Period for the slow EMA (default 26).
        signal_period: Period for the signal line EMA (default 9).

    Returns:
        Tuple containing (macd_line, signal_line, histogram) for the most recent candle.

    Raises:
        ValueError: If insufficient data is provided.
    """
    if fast_period <= 0 or slow_period <= 0 or signal_period <= 0:
        raise ValueError("All periods must be positive integers")
    if fast_period >= slow_period:
        raise ValueError("fast_period must be smaller than slow_period")
    if len(closes) < slow_period + signal_period:
        raise ValueError(
            f"At least {slow_period + signal_period} closing prices are required"
        )

    # Compute EMAs
    fast_ema = _ema(closes, fast_period)
    slow_ema = _ema(closes, slow_period)

    # Align fast EMA to the length of slow EMA
    # fast_ema starts at index fast_period-1, slow_ema at slow_period-1
    # Trim the earlier part of fast_ema so both lists align on the same timestamps
    align_offset = slow_period - fast_period
    fast_aligned = fast_ema[align_offset:]

    macd_line_series = [f - s for f, s in zip(fast_aligned, slow_ema)]

    # Signal line is EMA of MACD line
    signal_line_series = _ema(macd_line_series, signal_period)

    # The latest values are the last elements of each series
    macd_line = macd_line_series[-1]
    signal_line = signal_line_series[-1]
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram