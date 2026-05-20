"""core/strategy_engine/htf_structure.py — D1 market structure gate (Phase 1 ICT migration).

Replaces the H4 ADX regime classifier with a proper Daily structure bias.
Resamples H4 candles → D1, detects swing highs/lows, identifies BOS direction.

WHY D1 structure beats ADX regime:
  - ADX measures trend strength but not direction relative to macro structure
  - D1 BOS tells us exactly which way institutional money is positioned
  - Trading WITH D1 structure = trading with smart money, not against it

Return interface matches RegimeClassifier so nothing else in the pipeline changes:
  {"signal_gate": "pass"|"blocked", "regime": str, "adx": float,
   "d1_bias": "bullish"|"bearish"|None, "d1_bos_level": float}
"""
from __future__ import annotations

import numpy as np
import pandas as pd


_SWING_N      = 3    # bars each side to confirm a D1 swing point
_MIN_D1_BARS  = 20   # minimum D1 bars needed for structure analysis
_BOS_LOOKBACK = 40   # D1 bars to scan for the most recent BOS


def _resample_h4_to_d1(h4_df: pd.DataFrame) -> pd.DataFrame:
    """Resample H4 OHLC to daily candles."""
    df = h4_df.copy()

    # Convert epoch int timestamps to datetime if needed
    if pd.api.types.is_integer_dtype(df["time"]):
        df["date"] = pd.to_datetime(df["time"], unit="s").dt.date
    else:
        df["date"] = pd.to_datetime(df["time"]).dt.date

    daily = df.groupby("date").agg(
        open   = ("open",   "first"),
        high   = ("high",   "max"),
        low    = ("low",    "min"),
        close  = ("close",  "last"),
        volume = ("volume", "sum"),
    ).reset_index()

    return daily.reset_index(drop=True)


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


def _blocked(reason: str) -> dict:
    return {
        "signal_gate": "blocked",
        "regime":      "ranging",
        "adx":         0.0,
        "d1_bias":     None,
        "d1_bos_level": None,
        "reason":      reason,
    }


class HTFStructure:
    """D1 market structure classifier — drop-in replacement for RegimeClassifier."""

    def classify(self, h4_df: pd.DataFrame) -> dict:
        """
        Classify D1 market structure from H4 data.

        Returns the same interface as RegimeClassifier.classify().
        """
        if h4_df is None or len(h4_df) < _MIN_D1_BARS * 4:
            return _blocked("insufficient_h4_bars")

        try:
            d1 = _resample_h4_to_d1(h4_df)
        except Exception:
            return _blocked("resample_failed")

        if len(d1) < _MIN_D1_BARS:
            return _blocked("insufficient_d1_bars")

        window = d1.iloc[-_BOS_LOOKBACK:].reset_index(drop=True)
        highs  = window["high"].values.astype(float)
        lows   = window["low"].values.astype(float)
        closes = window["close"].values.astype(float)

        last_close = float(closes[-1])

        swing_highs = _find_swing_highs(highs)
        swing_lows  = _find_swing_lows(lows)

        if not swing_highs or not swing_lows:
            return _blocked("no_d1_swing_points")

        # ── Determine D1 structure bias ───────────────────────────────────────
        # Bullish BOS: current close is above the most recent swing high
        # Bearish BOS: current close is below the most recent swing low
        last_sh = float(highs[swing_highs[-1]])
        last_sl = float(lows[swing_lows[-1]])

        # Also check the second-to-last swings for higher-high / lower-low structure
        prev_sh = float(highs[swing_highs[-2]]) if len(swing_highs) >= 2 else last_sh
        prev_sl = float(lows[swing_lows[-2]])   if len(swing_lows)  >= 2 else last_sl

        bullish_structure = (last_sh > prev_sh) and (last_sl > prev_sl)
        bearish_structure = (last_sh < prev_sh) and (last_sl < prev_sl)

        # BOS confirmation: close broke above last swing high (bullish) or below last swing low (bearish)
        bullish_bos = last_close > last_sh
        bearish_bos = last_close < last_sl

        if bullish_structure or bullish_bos:
            d1_bias    = "bullish"
            bos_level  = last_sh
            regime     = "trending"
        elif bearish_structure or bearish_bos:
            d1_bias    = "bearish"
            bos_level  = last_sl
            regime     = "trending"
        else:
            # No clear D1 structure — block the trade
            return _blocked("no_d1_structure")

        # Volatility check: if daily ATR is abnormally large → volatile regime (half lot)
        daily_ranges = highs - lows
        avg_range    = float(daily_ranges[-20:].mean()) if len(daily_ranges) >= 20 else float(daily_ranges.mean())
        recent_range = float(daily_ranges[-3:].mean())
        is_volatile  = recent_range > avg_range * 2.0

        return {
            "signal_gate":  "pass",
            "regime":       "volatile" if is_volatile else regime,
            "adx":          round(float(recent_range / avg_range * 25), 1),  # synthetic ADX-like score
            "d1_bias":      d1_bias,
            "d1_bos_level": round(bos_level, 5),
            "reason":       f"d1_{d1_bias}_structure",
        }
