"""core/strategy_engine/fvg_detector.py — Fair Value Gap (FVG) detection.

Phase 3 of the ICT migration. Added as Gate 3b after Order Block confirmation.

WHAT IS AN FVG:
  A 3-candle imbalance where the impulse candle moves so fast that price leaves
  a gap between candle[i-1] and candle[i+1]:

  Bullish FVG:  candle[i-1].high < candle[i+1].low
                (gap between prior high and next low — price moved up leaving imbalance)

  Bearish FVG:  candle[i-1].low  > candle[i+1].high
                (gap between prior low and next high — price moved down leaving imbalance)

WHY FVGs IMPROVE WR:
  - FVGs mark where institutions moved price aggressively, leaving unfilled orders
  - Price is "attracted" back to fill the imbalance (50-75% FVG fill before continuing)
  - Entering at an unmitigated FVG inside an OB = two institutional confluences
  - Tighter entry = tighter SL = better R:R

ENTRY:
  Price retraces into the FVG zone (between fvg_bottom and fvg_top).
  The FVG must be unmitigated — price hasn't fully closed through it yet.

Return: {"passed": bool, "reason": str, "fvg_top": float, "fvg_bottom": float}
"""
from __future__ import annotations

import numpy as np
import pandas as pd


_LOOKBACK    = 60   # M15 bars to scan for FVGs
_MAX_FVG_AGE = 50   # M15 bars — FVGs older than this have likely been filled
_MIN_FVG_SIZE_MULT = 0.3  # FVG must be ≥ 30% of avg candle range (filters noise)


def _avg_range(df: pd.DataFrame, n: int = 20) -> float:
    highs  = df["high"].values.astype(float)
    lows   = df["low"].values.astype(float)
    ranges = highs - lows
    tail   = ranges[-min(n, len(ranges)):]
    return float(tail.mean()) if len(tail) > 0 else 0.0


def check_fvg(
    df: pd.DataFrame,
    direction: str,
) -> dict:
    """
    Find the most recent unmitigated FVG aligned with `direction`.

    Returns:
        {"passed": bool, "reason": str, "fvg_top": float, "fvg_bottom": float}
    """
    if df is None or len(df) < 10:
        return {"passed": False, "reason": "insufficient_bars_for_fvg",
                "fvg_top": 0.0, "fvg_bottom": 0.0}

    window   = df.iloc[-_LOOKBACK:].reset_index(drop=True) if len(df) > _LOOKBACK else df.reset_index(drop=True)
    highs    = window["high"].values.astype(float)
    lows     = window["low"].values.astype(float)
    closes   = window["close"].values.astype(float)
    n        = len(window)

    last_close = float(closes[-1])
    avg_rng    = _avg_range(window)
    min_size   = avg_rng * _MIN_FVG_SIZE_MULT
    last_idx   = n - 1

    best_fvg: dict | None = None

    # Scan backwards — most recent unmitigated FVG wins
    for i in range(n - 3, max(0, n - _MAX_FVG_AGE), -1):
        if direction == "bullish":
            # Bullish FVG: gap between candle[i].high and candle[i+2].low
            fvg_bottom = highs[i]
            fvg_top    = lows[i + 2]

            if fvg_top <= fvg_bottom:
                continue  # no gap
            if (fvg_top - fvg_bottom) < min_size:
                continue  # gap too small — noise

            # Unmitigated: no close below fvg_bottom after the FVG formed
            post_closes = closes[i + 2 : last_idx + 1]
            if len(post_closes) > 0 and min(post_closes) < fvg_bottom:
                continue  # FVG fully mitigated

            # Price must be at or approaching the FVG (retracing into it)
            inside_fvg    = fvg_bottom <= last_close <= fvg_top
            approaching   = last_close <= fvg_top * 1.003  # within 0.3% above FVG top

            if inside_fvg or approaching:
                best_fvg = {
                    "fvg_top":    round(fvg_top, 6),
                    "fvg_bottom": round(fvg_bottom, 6),
                    "age":        last_idx - i,
                }
                break

        else:  # bearish
            # Bearish FVG: gap between candle[i].low and candle[i+2].high
            fvg_top    = lows[i]
            fvg_bottom = highs[i + 2]

            if fvg_bottom >= fvg_top:
                continue  # no gap
            if (fvg_top - fvg_bottom) < min_size:
                continue  # gap too small

            # Unmitigated: no close above fvg_top after the FVG formed
            post_closes = closes[i + 2 : last_idx + 1]
            if len(post_closes) > 0 and max(post_closes) > fvg_top:
                continue  # FVG fully mitigated

            inside_fvg  = fvg_bottom <= last_close <= fvg_top
            approaching = last_close >= fvg_bottom * 0.997  # within 0.3% below FVG bottom

            if inside_fvg or approaching:
                best_fvg = {
                    "fvg_top":    round(fvg_top, 6),
                    "fvg_bottom": round(fvg_bottom, 6),
                    "age":        last_idx - i,
                }
                break

    if best_fvg is None:
        return {"passed": False,
                "reason": f"no_unmitigated_{'bullish' if direction == 'bullish' else 'bearish'}_fvg",
                "fvg_top": 0.0, "fvg_bottom": 0.0}

    return {
        "passed":     True,
        "reason":     f"{'bullish' if direction == 'bullish' else 'bearish'}_fvg_confirmed",
        "fvg_top":    best_fvg["fvg_top"],
        "fvg_bottom": best_fvg["fvg_bottom"],
        "fvg_age":    best_fvg["age"],
    }
