"""core/strategy_engine/bias_analyzer.py — HTF directional bias analysis."""
from __future__ import annotations

import pandas as pd


class BiasAnalyzer:
    """Determine higher-timeframe directional bias from OHLC data."""

    def analyze(self, htf_df: pd.DataFrame, symbol: str = "") -> dict:
        return {"direction": None, "strength": 0.0, "reason": "no_htf_bias"}
