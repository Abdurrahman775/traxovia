"""core/strategy_engine/liquidity_sweep.py — Liquidity sweep detection.

Phase 4a of the ICT migration. Replaces Entry Analyzer as Gate 4.

WHAT IS A LIQUIDITY SWEEP:
  Institutions hunt stop losses clustered at equal highs/lows before reversing.
  A sweep = price briefly wicks beyond a prior swing (takes the stops), then
  immediately closes back inside (reversal begins).

  Bullish sweep:  wick below a prior swing low (equal lows),
                  then candle closes back above that level.
  Bearish sweep:  wick above a prior swing high (equal highs),
                  then candle closes back below that level.

WHY THIS IMPROVES WR:
  - Confirms institutions took stop-loss liquidity (fuel for the reversal)
  - Without a sweep, zone touches are often just noise — not institutional
  - With a sweep, smart money has accumulated and the move is genuine

Return: {"passed": bool, "reason": str, "sweep_price": float, "sweep_bar": int}
"""
from __future__ import annotations

import numpy as np
import pandas as pd


_LOOKBACK        = 40    # M15 bars to scan for sweep
_EQUAL_TOLERANCE = 0.0008  # 0.08% — tight equal highs/lows (genuine stop hunts only)
_MIN_SWING_N     = 3    # bars each side — more robust swing confirmation
_MIN_WICK_MULT   = 0.5  # sweep wick must be ≥ 50% of candle range (decisive pin bar)


def _find_swing_lows(lows: np.ndarray, n: int = _MIN_SWING_N) -> list[int]:
    result = []
    for i in range(n, len(lows) - n):
        if all(lows[i] <= lows[i - j] for j in range(1, n + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, n + 1)):
            result.append(i)
    return result


def _find_swing_highs(highs: np.ndarray, n: int = _MIN_SWING_N) -> list[int]:
    result = []
    for i in range(n, len(highs) - n):
        if all(highs[i] >= highs[i - j] for j in range(1, n + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, n + 1)):
            result.append(i)
    return result


def check_liquidity_sweep(df: pd.DataFrame, direction: str) -> dict:
    """
    Check if a liquidity sweep occurred in the recent bars of `df`.

    Returns:
        {"passed": bool, "reason": str, "sweep_price": float, "sweep_bar": int}
    """
    if df is None or len(df) < 20:
        return {"passed": False, "reason": "insufficient_bars", "sweep_price": 0.0, "sweep_bar": -1}

    window = df.iloc[-_LOOKBACK:].reset_index(drop=True) if len(df) > _LOOKBACK else df.reset_index(drop=True)
    highs  = window["high"].values.astype(float)
    lows   = window["low"].values.astype(float)
    opens  = window["open"].values.astype(float)
    closes = window["close"].values.astype(float)
    n      = len(window)

    if direction == "bullish":
        # Look for a bullish sweep: wick below a prior swing low, close back above it
        swing_lows = _find_swing_lows(lows[:-3])  # exclude last 3 bars — we need prior swings
        if not swing_lows:
            return {"passed": False, "reason": "no_prior_swing_lows",
                    "sweep_price": 0.0, "sweep_bar": -1}

        # Check the last 5 bars for a sweep candle
        for sweep_idx in range(n - 3, n):
            if sweep_idx < 0:
                continue
            candle_low   = lows[sweep_idx]
            candle_close = closes[sweep_idx]
            candle_high  = highs[sweep_idx]
            candle_range = candle_high - candle_low
            if candle_range == 0:
                continue

            for sl_idx in swing_lows:
                if sl_idx >= sweep_idx:
                    continue
                swing_low_price = lows[sl_idx]

                # Equal lows: prior swing low within tolerance
                equal = abs(candle_low - swing_low_price) / swing_low_price <= _EQUAL_TOLERANCE
                # Or direct sweep: wicked below prior swing low
                swept = candle_low < swing_low_price

                if not (equal or swept):
                    continue

                # Confirm close back above the swing low (reversal)
                if candle_close <= swing_low_price:
                    continue

                # Wick size check — low wick must be meaningful
                low_wick = min(opens[sweep_idx], candle_close) - candle_low
                if low_wick / candle_range < _MIN_WICK_MULT:
                    continue

                return {
                    "passed":      True,
                    "reason":      "bullish_liquidity_sweep",
                    "sweep_price": round(candle_low, 6),
                    "sweep_bar":   sweep_idx,
                    "swing_low":   round(swing_low_price, 6),
                }

        return {"passed": False, "reason": "no_bullish_sweep_found",
                "sweep_price": 0.0, "sweep_bar": -1}

    else:  # bearish
        swing_highs = _find_swing_highs(highs[:-3])
        if not swing_highs:
            return {"passed": False, "reason": "no_prior_swing_highs",
                    "sweep_price": 0.0, "sweep_bar": -1}

        for sweep_idx in range(n - 3, n):
            if sweep_idx < 0:
                continue
            candle_high  = highs[sweep_idx]
            candle_close = closes[sweep_idx]
            candle_low   = lows[sweep_idx]
            candle_range = candle_high - candle_low
            if candle_range == 0:
                continue

            for sh_idx in swing_highs:
                if sh_idx >= sweep_idx:
                    continue
                swing_high_price = highs[sh_idx]

                equal = abs(candle_high - swing_high_price) / swing_high_price <= _EQUAL_TOLERANCE
                swept = candle_high > swing_high_price

                if not (equal or swept):
                    continue

                if candle_close >= swing_high_price:
                    continue

                high_wick = candle_high - max(opens[sweep_idx], candle_close)
                if high_wick / candle_range < _MIN_WICK_MULT:
                    continue

                return {
                    "passed":       True,
                    "reason":       "bearish_liquidity_sweep",
                    "sweep_price":  round(candle_high, 6),
                    "sweep_bar":    sweep_idx,
                    "swing_high":   round(swing_high_price, 6),
                }

        return {"passed": False, "reason": "no_bearish_sweep_found",
                "sweep_price": 0.0, "sweep_bar": -1}
