"""core/strategy_engine/bias_analyzer.py — HTF directional bias via BOS detection."""
from __future__ import annotations

import pandas as pd

from core.structure_engine.bos_identifier import BOSIdentifier

_MAX_BOS_AGE = 20   # H4 bars (~3 days); older than this = stale, treat as no bias


class BiasAnalyzer:
    def __init__(self, n: int = 3):
        self._bos = BOSIdentifier(n=n)

    def analyze(self, htf_df: pd.DataFrame, symbol: str = "") -> dict:
        min_bars = self._bos.n * 2 + 5
        if htf_df is None or len(htf_df) < min_bars:
            return {"direction": None, "strength": 0.0, "bos_strength": 0.0,
                    "bars_since_bos": 0, "reason": "insufficient_data"}

        df        = self._bos.identify(htf_df)
        last_idx  = len(df) - 1

        bull_pos = [i for i, v in enumerate(df["bullish_bos"]) if v]
        bear_pos = [i for i, v in enumerate(df["bearish_bos"]) if v]

        last_bull = bull_pos[-1] if bull_pos else -1
        last_bear = bear_pos[-1] if bear_pos else -1

        if last_bull == -1 and last_bear == -1:
            return {"direction": None, "strength": 0.0, "bos_strength": 0.0,
                    "bars_since_bos": 0, "reason": "no_bos_found"}

        if last_bull >= last_bear:
            direction = "bullish"
            bos_idx   = last_bull
        else:
            direction = "bearish"
            bos_idx   = last_bear

        bars_since = last_idx - bos_idx
        if bars_since > _MAX_BOS_AGE:
            return {"direction": None, "strength": 0.0, "bos_strength": 0.0,
                    "bars_since_bos": bars_since, "reason": "bos_too_old"}

        # Strength decays linearly: 1.0 at the BOS bar → 0.3 at _MAX_BOS_AGE
        strength = max(0.3, 1.0 - (bars_since / _MAX_BOS_AGE) * 0.7)

        # BOS magnitude: price displacement since the BOS level, normalised
        bos_close  = float(df["close"].iloc[bos_idx])
        curr_close = float(df["close"].iloc[-1])
        bos_strength = min(1.0, abs(curr_close - bos_close) / max(bos_close, 1e-8) * 200)

        return {
            "direction":      direction,
            "strength":       round(strength, 3),
            "bos_strength":   round(bos_strength, 3),
            "bars_since_bos": bars_since,
            "reason":         f"bos_{direction}",
        }
