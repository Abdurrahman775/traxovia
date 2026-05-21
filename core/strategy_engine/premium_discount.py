"""core/strategy_engine/premium_discount.py — ICT Premium/Discount zone filter.

Gate 2b: Only enter when price is on the correct side of the 50% equilibrium
(midpoint) of the most recent D1 swing range.

  Bullish setup → price must be in DISCOUNT (below 50% of range)
  Bearish setup → price must be in PREMIUM (above 50% of range)

WHY THIS IMPROVES WR:
  Buying in premium or selling in discount means chasing — institutions have
  already positioned and are now offloading against late retail entries.
  Waiting for price to retrace to discount/premium ensures we enter with
  smart money, not against it.

Return:
  {
    "passed":       bool,
    "reason":       str,
    "zone":         "premium" | "discount" | "equilibrium",
    "equilibrium":  float,
    "range_high":   float,
    "range_low":    float,
    "pct_position": float,   # 0.0 = range low, 1.0 = range high
  }
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_SWING_N     = 3    # bars each side to confirm a swing
_LOOKBACK    = 40   # H4 bars to scan for the defining swing range (~1 week)
_EQ_BUFFER   = 0.05 # 5% buffer around equilibrium — wider band avoids blocking local pullbacks


def _find_swing_highs(highs: np.ndarray, n: int = _SWING_N) -> list[int]:
    result = []
    for i in range(n, len(highs) - n):
        if all(highs[i] >= highs[i - j] for j in range(1, n + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, n + 1)):
            result.append(i)
    return result


def _find_swing_lows(lows: np.ndarray, n: int = _SWING_N) -> list[int]:
    result = []
    for i in range(n, len(lows) - n):
        if all(lows[i] <= lows[i - j] for j in range(1, n + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, n + 1)):
            result.append(i)
    return result


def check_premium_discount(df: pd.DataFrame, direction: str) -> dict:
    """
    Check if the most recent close is in premium or discount.

    Args:
        df:        H4 OHLC DataFrame (needs at least _LOOKBACK bars)
        direction: "bullish" or "bearish"
    """
    if df is None or len(df) < _SWING_N * 2 + 5:
        return {
            "passed": True, "reason": "insufficient_bars_skip",
            "zone": "unknown", "equilibrium": 0.0,
            "range_high": 0.0, "range_low": 0.0, "pct_position": 0.5,
        }

    window = df.iloc[-_LOOKBACK:].reset_index(drop=True) if len(df) > _LOOKBACK else df.reset_index(drop=True)
    highs  = window["high"].values.astype(float)
    lows   = window["low"].values.astype(float)
    closes = window["close"].values.astype(float)

    current_price = float(closes[-1])

    # Find most recent confirmed swing high and swing low
    swing_highs = _find_swing_highs(highs[:-_SWING_N])  # exclude last n unconfirmed
    swing_lows  = _find_swing_lows(lows[:-_SWING_N])

    if not swing_highs or not swing_lows:
        return {
            "passed": True, "reason": "no_swings_skip",
            "zone": "unknown", "equilibrium": 0.0,
            "range_high": 0.0, "range_low": 0.0, "pct_position": 0.5,
        }

    range_high = float(highs[swing_highs[-1]])
    range_low  = float(lows[swing_lows[-1]])

    # Ensure valid range
    if range_high <= range_low:
        range_high = float(highs[swing_highs[-1]])
        range_low  = float(lows[swing_lows[-1]])
        if range_high <= range_low:
            return {
                "passed": True, "reason": "invalid_range_skip",
                "zone": "unknown", "equilibrium": 0.0,
                "range_high": range_high, "range_low": range_low, "pct_position": 0.5,
            }

    equilibrium  = (range_high + range_low) / 2.0
    range_size   = range_high - range_low
    pct_position = (current_price - range_low) / range_size  # 0.0=low, 1.0=high

    # Determine zone with buffer around equilibrium
    eq_low  = equilibrium - range_size * _EQ_BUFFER
    eq_high = equilibrium + range_size * _EQ_BUFFER

    if current_price < eq_low:
        zone = "discount"
    elif current_price > eq_high:
        zone = "premium"
    else:
        zone = "equilibrium"

    meta = {
        "zone":         zone,
        "equilibrium":  round(equilibrium, 5),
        "range_high":   round(range_high, 5),
        "range_low":    round(range_low, 5),
        "pct_position": round(pct_position, 4),
    }

    # Bullish: need discount or equilibrium (avoid entering in premium)
    if direction == "bullish":
        if zone == "premium":
            return {"passed": False, "reason": "bullish_in_premium", **meta}
        return {"passed": True, "reason": f"bullish_in_{zone}", **meta}

    # Bearish: need premium or equilibrium (avoid entering in discount)
    else:
        if zone == "discount":
            return {"passed": False, "reason": "bearish_in_discount", **meta}
        return {"passed": True, "reason": f"bearish_in_{zone}", **meta}
