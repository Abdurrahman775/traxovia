"""core/structure_engine/regime_classifier.py — Market regime classification."""
from __future__ import annotations

import pandas as pd


class RegimeClassifier:
    """Classify market regime using ADX and ATR-to-volatility ratio.

    Volatile check runs first (per test_phase3 comment).
    Trending vs ranging is then decided by ADX threshold.
    """

    _ADX_THRESHOLD       = 20.0
    _ATR_RATIO_THRESHOLD = 2.0

    def classify(self, df: pd.DataFrame) -> dict:
        adx = self._calc_adx(df)
        atr = self._calc_atr(df)

        vol           = df["close"].pct_change().rolling(20).std().iloc[-1]
        current_price = float(df["close"].iloc[-1])
        if pd.isna(vol) or vol == 0:
            atr_ratio = float("inf") if atr > 0 else 0.0
        else:
            atr_ratio = atr / (vol * current_price)

        if atr_ratio > self._ATR_RATIO_THRESHOLD:
            regime, gate = "volatile", "reduced"
        elif adx >= self._ADX_THRESHOLD:
            regime, gate = "trending", "open"
        else:
            regime, gate = "ranging", "blocked"

        return {"regime": regime, "adx": adx,
                "atr_ratio": atr_ratio, "signal_gate": gate}

    def _calc_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        high  = df["high"]
        low   = df["low"]
        close = df["close"]

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)

        up   = high.diff()
        down = -low.diff()

        plus_dm  = up.where((up > down) & (up > 0),     0.0)
        minus_dm = down.where((down > up) & (down > 0), 0.0)

        alpha    = 1 / period
        atr_s    = tr.ewm(alpha=alpha, adjust=False).mean()
        nan_safe = atr_s.replace(0, float("nan"))
        plus_di  = 100 * plus_dm.ewm(alpha=alpha,  adjust=False).mean() / nan_safe
        minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / nan_safe

        dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
        adx = dx.ewm(alpha=alpha, adjust=False).mean()
        val = adx.iloc[-1]
        return float(val) if pd.notna(val) else 0.0

    def _calc_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        high  = df["high"]
        low   = df["low"]
        close = df["close"]

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)

        atr = tr.ewm(alpha=1 / period, adjust=False).mean()
        val = atr.iloc[-1]
        return float(val) if pd.notna(val) else 0.0
