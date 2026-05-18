"""core/strategy_engine/entry_analyzer.py — M15 entry confirmation gate."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    high  = df["high"].values.astype(float)
    low   = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    if len(close) < 2:
        return float(high[-1] - low[-1]) if len(high) > 0 else 0.0
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:]  - close[:-1]),
        ),
    )
    tail = tr[-min(period, len(tr)):]
    return float(tail.mean()) if len(tail) > 0 else 0.0


def _pip_mult(price: float) -> float:
    if price > 500:  return 10.0      # XAUUSD
    if price > 50:   return 100.0     # USDJPY
    return 10_000.0                   # EURUSD, GBPUSD, AUDUSD


def _recent_higher_highs(df: pd.DataFrame, bars: int = 5) -> bool:
    """True if the last `bars` M15 candles are making higher highs (uptrend)."""
    highs = df["high"].values.astype(float)[-bars:]
    return all(highs[i] >= highs[i - 1] for i in range(1, len(highs)))


def _recent_lower_lows(df: pd.DataFrame, bars: int = 5) -> bool:
    """True if the last `bars` M15 candles are making lower lows (downtrend)."""
    lows = df["low"].values.astype(float)[-bars:]
    return all(lows[i] <= lows[i - 1] for i in range(1, len(lows)))


class EntryAnalyzer:
    _SL_ATR_MULT    = 2.0   # widened from 1.5 — gives trades room to breathe
    _TP_RR          = 3.0   # R:R ratio (raised from 2.0)
    _MIN_SL_PIPS    = 5.0   # raised from 3.0 — reject unrealistically tight SLs
    _MIN_BODY_FRAC  = 0.40  # candle body must be ≥ 40% of range (raised from 35%)
    _MIN_BIAS_STR   = 0.60  # bias strength must be ≥ 0.6 (fresh BOS only)
    _COUNTER_BARS   = 8     # bars to check for counter-trend structure (raised from 5)

    def check_gate(
        self,
        df: pd.DataFrame,
        bias: dict | None = None,
        zone: dict | None = None,
    ) -> dict:
        if not bias or not zone or not zone.get("passed"):
            return {"passed": False, "reason": "no_zone_or_bias"}

        direction = bias.get("direction")
        z         = zone.get("zone")
        if not direction or not z:
            return {"passed": False, "reason": "missing_direction_or_zone"}

        if (bias.get("strength") or 0.0) < self._MIN_BIAS_STR:
            return {"passed": False, "reason": "bias_too_weak"}

        if df is None or len(df) < 10:
            return {"passed": False, "reason": "insufficient_ltf_data"}

        last = df.iloc[-1]
        prev = df.iloc[-2]

        o = float(last["open"])
        h = float(last["high"])
        l = float(last["low"])
        c = float(last["close"])

        body       = abs(c - o)
        candle_rng = h - l or abs(c) * 0.001
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)
        body_frac  = body / candle_rng if candle_rng > 0 else 0.0

        atr = _atr(df) or candle_rng
        pip = _pip_mult(c)

        # ── Entry confirmation ─────────────────────────────────────────────────
        # Require a meaningful candle — reject dojis and tiny-body candles.
        # For bearish: the signal candle must close below its open AND have
        #   a body that is at least 35% of the candle range, OR be a strong
        #   pin bar / engulfing. A plain bearish close alone is insufficient.
        # For bullish: mirror logic applies.
        if direction == "bullish":
            strong_close = c > o and body_frac >= self._MIN_BODY_FRAC
            pin_bar      = (lower_wick >= 2 * body) if body > 0 else (lower_wick > candle_rng * 0.6)
            engulfing    = c > float(prev["high"]) and o <= float(prev["close"])
            confirmed    = strong_close or pin_bar or engulfing
            # Reject if short-term M15 structure is making lower lows (counter-trend)
            if confirmed and _recent_lower_lows(df, bars=self._COUNTER_BARS):
                return {"passed": False, "reason": "m15_trending_against_bias"}
        else:
            strong_close = c < o and body_frac >= self._MIN_BODY_FRAC
            pin_bar      = (upper_wick >= 2 * body) if body > 0 else (upper_wick > candle_rng * 0.6)
            engulfing    = c < float(prev["low"]) and o >= float(prev["close"])
            confirmed    = strong_close or pin_bar or engulfing
            # Reject if short-term M15 structure is making higher highs (counter-trend)
            if confirmed and _recent_higher_highs(df, bars=self._COUNTER_BARS):
                return {"passed": False, "reason": "m15_trending_against_bias"}

        if not confirmed:
            return {"passed": False, "reason": "no_entry_candle"}

        # ── SL / TP calculation ────────────────────────────────────────────────
        entry_price = c

        if direction == "bullish":
            sl_price = min(z.bottom - self._SL_ATR_MULT * atr, l - atr * 0.5)
            sl_dist  = entry_price - sl_price
            tp_price = entry_price + sl_dist * self._TP_RR
        else:
            sl_price = max(z.top + self._SL_ATR_MULT * atr, h + atr * 0.5)
            sl_dist  = sl_price - entry_price
            tp_price = entry_price - sl_dist * self._TP_RR

        if sl_dist <= 0:
            return {"passed": False, "reason": "zero_sl_distance"}

        sl_pips = round(sl_dist * pip, 1)
        tp_pips = round(sl_dist * self._TP_RR * pip, 1)

        if sl_pips < self._MIN_SL_PIPS:
            return {"passed": False, "reason": "sl_too_tight"}

        return {
            "passed":      True,
            "entry_price": round(entry_price, 6),
            "sl_price":    round(sl_price, 6),
            "tp_price":    round(tp_price, 6),
            "sl_pips":     sl_pips,
            "tp_pips":     tp_pips,
            "reason":      "entry_confirmed",
        }
