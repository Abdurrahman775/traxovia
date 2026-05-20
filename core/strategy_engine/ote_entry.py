"""core/strategy_engine/ote_entry.py — Optimal Trade Entry (OTE) calculation.

Phase 4b of the ICT migration. Works with liquidity_sweep to define the
precise entry zone using Fibonacci retracement.

WHAT IS OTE:
  After a liquidity sweep + CHOCH, institutions re-enter at the 0.618–0.786
  Fibonacci retracement of the sweep-to-structure-break move.

  This "golden zone" (0.618–0.786) is where:
    - Smart money absorbs remaining retail orders against the trend
    - Price has the highest probability of continuing in the new direction
    - SL behind the sweep low/high = tightest possible SL

  Bullish OTE:
    Swing = from sweep_low to choch_high (the structural break)
    OTE zone = [sweep_low + 0.618×swing, sweep_low + 0.786×swing]
    Entry = 0.705 Fibonacci level (midpoint of golden zone)
    SL = below sweep_low − buffer

  Bearish OTE:
    Swing = from sweep_high to choch_low
    OTE zone = [sweep_high − 0.786×swing, sweep_high − 0.618×swing]
    Entry = 0.705 Fibonacci level
    SL = above sweep_high + buffer

Return: {"passed": bool, "entry_price": float, "sl_price": float,
         "tp_price": float, "sl_pips": float, "tp_pips": float,
         "ote_top": float, "ote_bottom": float}
"""
from __future__ import annotations

import numpy as np
import pandas as pd


_FIB_LOW  = 0.618
_FIB_HIGH = 0.786
_FIB_ENTRY = (_FIB_LOW + _FIB_HIGH) / 2  # 0.702 midpoint
_SL_BUFFER_MULT = 0.5   # SL = sweep_price ± ATR × 0.5
_TP_RR          = 3.0   # 3R take profit
_MIN_SL_PIPS    = 3.0


def _atr(df: pd.DataFrame, period: int = 10) -> float:
    high  = df["high"].values.astype(float)
    low   = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    if len(close) < 2:
        return float(high[-1] - low[-1]) if len(high) > 0 else 0.0
    tr   = np.maximum(high[1:] - low[1:],
           np.maximum(np.abs(high[1:] - close[:-1]),
                      np.abs(low[1:]  - close[:-1])))
    tail = tr[-min(period, len(tr)):]
    return float(tail.mean()) if len(tail) > 0 else 0.0


def _pip_mult(price: float) -> float:
    if price > 500:  return 10.0
    if price > 50:   return 100.0
    return 10_000.0


def calculate_ote(
    df: pd.DataFrame,
    direction: str,
    sweep_price: float,
    choch_level: float,
) -> dict:
    """
    Calculate the OTE entry zone from sweep price and CHOCH level.

    Args:
        df:           M15/M5 window
        direction:    "bullish" or "bearish"
        sweep_price:  price of the liquidity sweep (low for bullish, high for bearish)
        choch_level:  the CHOCH structural break level

    Returns entry parameters compatible with CHOCH detector output interface.
    """
    def _failed(reason: str) -> dict:
        return {"passed": False, "reason": reason, "entry_price": 0.0,
                "sl_price": 0.0, "tp_price": 0.0, "sl_pips": 0.0, "tp_pips": 0.0}

    if df is None or len(df) < 5:
        return _failed("insufficient_data")

    last_close = float(df["close"].iloc[-1])
    atr        = _atr(df)
    pip        = _pip_mult(last_close)

    if direction == "bullish":
        # Swing = sweep_low → choch_high
        swing = choch_level - sweep_price
        if swing <= 0:
            return _failed("invalid_bullish_swing")

        ote_bottom = sweep_price + _FIB_LOW  * swing
        ote_top    = sweep_price + _FIB_HIGH * swing
        entry      = sweep_price + _FIB_ENTRY * swing

        # Price must have retraced into OTE zone (or be inside it)
        if last_close > ote_top * 1.001:
            return _failed(f"price_above_ote_zone_{last_close:.5f}>{ote_top:.5f}")

        # SL below sweep low with ATR buffer
        sl_price = sweep_price - atr * _SL_BUFFER_MULT
        sl_dist  = entry - sl_price
        if sl_dist <= 0:
            return _failed("zero_sl_dist")

        sl_pips = round(sl_dist * pip, 1)
        if sl_pips < _MIN_SL_PIPS:
            return _failed("sl_too_tight")

        tp_price = entry + sl_dist * _TP_RR
        tp_pips  = round(sl_dist * _TP_RR * pip, 1)

        return {
            "passed":      True,
            "reason":      "bullish_ote_entry",
            "entry_price": round(entry, 6),
            "sl_price":    round(sl_price, 6),
            "tp_price":    round(tp_price, 6),
            "sl_pips":     sl_pips,
            "tp_pips":     tp_pips,
            "ote_top":     round(ote_top, 6),
            "ote_bottom":  round(ote_bottom, 6),
        }

    else:  # bearish
        swing = sweep_price - choch_level
        if swing <= 0:
            return _failed("invalid_bearish_swing")

        ote_top    = sweep_price - _FIB_LOW  * swing
        ote_bottom = sweep_price - _FIB_HIGH * swing
        entry      = sweep_price - _FIB_ENTRY * swing

        if last_close < ote_bottom * 0.999:
            return _failed(f"price_below_ote_zone_{last_close:.5f}<{ote_bottom:.5f}")

        sl_price = sweep_price + atr * _SL_BUFFER_MULT
        sl_dist  = sl_price - entry
        if sl_dist <= 0:
            return _failed("zero_sl_dist")

        sl_pips = round(sl_dist * pip, 1)
        if sl_pips < _MIN_SL_PIPS:
            return _failed("sl_too_tight")

        tp_price = entry - sl_dist * _TP_RR
        tp_pips  = round(sl_dist * _TP_RR * pip, 1)

        return {
            "passed":      True,
            "reason":      "bearish_ote_entry",
            "entry_price": round(entry, 6),
            "sl_price":    round(sl_price, 6),
            "tp_price":    round(tp_price, 6),
            "sl_pips":     sl_pips,
            "tp_pips":     tp_pips,
            "ote_top":     round(ote_top, 6),
            "ote_bottom":  round(ote_bottom, 6),
        }
