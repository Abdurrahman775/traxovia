"""core/strategy_engine/choch_detector.py — Change of Character (CHOCH) entry gate.

After the M15 zone gate passes, this gate drops to a lower timeframe (M5 live,
M15 proxy in backtest) and waits for a micro-BOS (Change of Character) confirming
institutional activity at the zone before entry.

WHY this matters vs plain M15 entry:
  - Tighter SL: placed behind the M5 swing rather than 2×ATR from zone bottom
  - Higher WR: confirms smart money actually reacted at the zone (not just touched it)
  - Better R:R: smaller SL at same 3R target = larger absolute profit per win

CHOCH definition:
  Bullish: price sweeps a swing low into the demand zone, then closes ABOVE
           the last swing high before that sweep (breaks bearish structure).
  Bearish: price sweeps a swing high into the supply zone, then closes BELOW
           the last swing low before that sweep (breaks bullish structure).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


_SWING_N  = 2   # bars each side to confirm a swing point
_LOOKBACK = 40  # bars to scan for swing points


def _find_swing_highs(highs: np.ndarray, n: int = _SWING_N) -> list[int]:
    """Return indices of swing highs (local maxima with n bars each side)."""
    result = []
    for i in range(n, len(highs) - n):
        if all(highs[i] >= highs[i - j] for j in range(1, n + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, n + 1)):
            result.append(i)
    return result


def _find_swing_lows(lows: np.ndarray, n: int = _SWING_N) -> list[int]:
    """Return indices of swing lows (local minima with n bars each side)."""
    result = []
    for i in range(n, len(lows) - n):
        if all(lows[i] <= lows[i - j] for j in range(1, n + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, n + 1)):
            result.append(i)
    return result


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


def detect_choch(
    df: pd.DataFrame,
    direction: str,
    min_sl_pips: float = 3.0,
    tp_rr: float = 3.0,
) -> dict:
    """
    Detect a Change of Character on `df` for the given bias direction.

    Returns:
        {"passed": bool, "reason": str, "entry_price": float,
         "sl_price": float, "tp_price": float, "sl_pips": float, "tp_pips": float}
    """
    if df is None or len(df) < _LOOKBACK:
        return {"passed": False, "reason": "insufficient_bars_for_choch"}

    window = df.iloc[-_LOOKBACK:].reset_index(drop=True)
    highs  = window["high"].values.astype(float)
    lows   = window["low"].values.astype(float)
    closes = window["close"].values.astype(float)

    last_close = float(closes[-1])
    atr        = _atr(window)
    pip        = _pip_mult(last_close)

    swing_highs = _find_swing_highs(highs)
    swing_lows  = _find_swing_lows(lows)

    if direction == "bullish":
        # Need: a swing low near the zone, then a close above the swing high
        # that formed after that swing low → confirms bullish CHOCH
        if not swing_lows:
            return {"passed": False, "reason": "no_swing_low_for_choch"}

        # Most recent swing low = the "liquidity sweep" into the demand zone
        sl_swing_idx = swing_lows[-1]
        sl_swing_price = float(lows[sl_swing_idx])

        # Find highest swing high AFTER the swing low
        post_swing_highs = [i for i in swing_highs if i > sl_swing_idx]
        if not post_swing_highs:
            return {"passed": False, "reason": "no_swing_high_after_swing_low"}

        choch_level = float(highs[post_swing_highs[-1]])

        # CHOCH confirmed: current close breaks above choch_level
        if last_close <= choch_level:
            return {"passed": False, "reason": f"choch_not_broken_need_{choch_level:.5f}"}

        # SL placed just below the swing low
        sl_price = sl_swing_price - atr * 0.5
        sl_dist  = last_close - sl_price
        if sl_dist <= 0:
            return {"passed": False, "reason": "choch_zero_sl"}

        sl_pips  = round(sl_dist * pip, 1)
        if sl_pips < min_sl_pips:
            return {"passed": False, "reason": "choch_sl_too_tight"}

        tp_price = last_close + sl_dist * tp_rr
        tp_pips  = round(sl_dist * tp_rr * pip, 1)

        return {
            "passed":      True,
            "reason":      "bullish_choch_confirmed",
            "entry_price": round(last_close, 6),
            "sl_price":    round(sl_price, 6),
            "tp_price":    round(tp_price, 6),
            "sl_pips":     sl_pips,
            "tp_pips":     tp_pips,
            "choch_level": round(choch_level, 6),
            "swing_low":   round(sl_swing_price, 6),
        }

    else:  # bearish
        if not swing_highs:
            return {"passed": False, "reason": "no_swing_high_for_choch"}

        # Most recent swing high = the "liquidity sweep" into the supply zone
        sh_swing_idx   = swing_highs[-1]
        sh_swing_price = float(highs[sh_swing_idx])

        # Find lowest swing low AFTER the swing high
        post_swing_lows = [i for i in swing_lows if i > sh_swing_idx]
        if not post_swing_lows:
            return {"passed": False, "reason": "no_swing_low_after_swing_high"}

        choch_level = float(lows[post_swing_lows[-1]])

        # CHOCH confirmed: current close breaks below choch_level
        if last_close >= choch_level:
            return {"passed": False, "reason": f"choch_not_broken_need_{choch_level:.5f}"}

        # SL placed just above the swing high
        sl_price = sh_swing_price + atr * 0.5
        sl_dist  = sl_price - last_close
        if sl_dist <= 0:
            return {"passed": False, "reason": "choch_zero_sl"}

        sl_pips  = round(sl_dist * pip, 1)
        if sl_pips < min_sl_pips:
            return {"passed": False, "reason": "choch_sl_too_tight"}

        tp_price = last_close - sl_dist * tp_rr
        tp_pips  = round(sl_dist * tp_rr * pip, 1)

        return {
            "passed":      True,
            "reason":      "bearish_choch_confirmed",
            "entry_price": round(last_close, 6),
            "sl_price":    round(sl_price, 6),
            "tp_price":    round(tp_price, 6),
            "sl_pips":     sl_pips,
            "tp_pips":     tp_pips,
            "choch_level": round(choch_level, 6),
            "swing_high":  round(sh_swing_price, 6),
        }
