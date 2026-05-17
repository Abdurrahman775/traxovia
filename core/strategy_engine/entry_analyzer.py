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
    """Return pips-per-unit based on price magnitude."""
    if price > 500:  return 10.0      # XAUUSD
    if price > 50:   return 100.0     # USDJPY
    return 10_000.0                   # EURUSD, GBPUSD, AUDUSD


class EntryAnalyzer:
    _SL_ATR_MULT = 1.5   # SL placed 1.5× ATR beyond the zone boundary
    _TP_RR       = 2.0   # minimum R:R ratio
    _MIN_SL_PIPS = 3.0   # reject if SL is unrealistically tight

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

        if df is None or len(df) < 5:
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

        atr = _atr(df) or candle_rng
        pip = _pip_mult(c)

        # ── Entry confirmation ─────────────────────────────────────────────────
        if direction == "bullish":
            bullish_close = c > o
            pin_bar       = (lower_wick >= 2 * body) if body > 0 else (lower_wick > candle_rng * 0.5)
            engulfing     = c > float(prev["high"]) and o <= float(prev["close"])
            confirmed     = bullish_close or pin_bar or engulfing
        else:
            bearish_close = c < o
            pin_bar       = (upper_wick >= 2 * body) if body > 0 else (upper_wick > candle_rng * 0.5)
            engulfing     = c < float(prev["low"]) and o >= float(prev["close"])
            confirmed     = bearish_close or pin_bar or engulfing

        if not confirmed:
            return {"passed": False, "reason": "no_entry_candle"}

        # ── SL / TP calculation ────────────────────────────────────────────────
        entry_price = c

        if direction == "bullish":
            # SL below zone bottom with ATR buffer; at least below the candle low
            sl_price = min(z.bottom - self._SL_ATR_MULT * atr, l - atr * 0.5)
            sl_dist  = entry_price - sl_price
            tp_price = entry_price + sl_dist * self._TP_RR
        else:
            # SL above zone top with ATR buffer; at least above the candle high
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
