"""core/ai_engine/feature_engineer.py — Extract 50 features from signal context."""
from __future__ import annotations
import numpy as np
import pandas as pd

FEATURE_NAMES = [
    # Regime (5)
    "adx", "atr_ratio", "regime_trending", "regime_ranging", "regime_volatile",
    # Bias (5)
    "bias_bullish", "bias_strength", "bos_strength", "bars_since_bos", "weekly_bias_bullish",
    # Zone (6)
    "in_demand_zone", "in_supply_zone", "zone_strength", "zone_test_count",
    "zone_top", "zone_bottom",
    # Entry (6)
    "entry_confirmed", "sl_pips", "tp_pips", "rr_ratio", "entry_price_norm", "sl_price_norm",
    # Weekly (4)
    "weekly_bos_strength", "bars_since_weekly_bos", "weekly_bullish", "weekly_bearish",
    # Spread (3)
    "current_spread", "spread_baseline", "spread_ratio",
    # Price action — HTF (8)
    "htf_close_norm", "htf_high_norm", "htf_low_norm", "htf_body_ratio",
    "htf_upper_wick", "htf_lower_wick", "htf_momentum", "htf_volatility",
    # Price action — LTF (8)
    "ltf_close_norm", "ltf_high_norm", "ltf_low_norm", "ltf_body_ratio",
    "ltf_upper_wick", "ltf_lower_wick", "ltf_momentum", "ltf_volatility",
    # Time (5)
    "hour_sin", "hour_cos", "day_sin", "day_cos", "session_london",
]

assert len(FEATURE_NAMES) == 50, f"FEATURE_NAMES must have 50 entries, got {len(FEATURE_NAMES)}"


class FeatureEngineer:
    def extract(self, ctx: dict) -> dict[str, float]:
        regime  = ctx.get("regime_info", {})
        bias    = ctx.get("bias_info", {})
        zone_i  = ctx.get("zone_info", {})
        entry_i = ctx.get("entry_info", {})
        weekly  = ctx.get("weekly_bias", {})
        spread  = ctx.get("spread", {})
        htf_df: pd.DataFrame = ctx.get("htf_df", pd.DataFrame())
        ltf_df: pd.DataFrame = ctx.get("ltf_df", pd.DataFrame())
        ts = ctx.get("timestamp", pd.Timestamp.now())

        zone = zone_i.get("zone")

        def _safe(v, default=0.0) -> float:
            try:
                f = float(v)
                return f if np.isfinite(f) else default
            except (TypeError, ValueError):
                return default

        def _ohlc_features(df: pd.DataFrame, prefix: str) -> dict[str, float]:
            if df is None or df.empty:
                return {f"{prefix}_{s}": 0.0 for s in
                        ["close_norm","high_norm","low_norm","body_ratio",
                         "upper_wick","lower_wick","momentum","volatility"]}
            row  = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else row
            c, h, l, o = _safe(row.get("close")), _safe(row.get("high")), _safe(row.get("low")), _safe(row.get("open"))
            body   = abs(c - o)
            rng    = h - l if h != l else 1e-8
            return {
                f"{prefix}_close_norm":  _safe(c / 1.1 - 1),
                f"{prefix}_high_norm":   _safe((h - c) / rng),
                f"{prefix}_low_norm":    _safe((c - l) / rng),
                f"{prefix}_body_ratio":  _safe(body / rng),
                f"{prefix}_upper_wick":  _safe((h - max(c, o)) / rng),
                f"{prefix}_lower_wick":  _safe((min(c, o) - l) / rng),
                f"{prefix}_momentum":    _safe((c - _safe(prev.get("close"))) / max(abs(_safe(prev.get("close"))), 1e-8)),
                f"{prefix}_volatility":  _safe(rng / max(c, 1e-8)),
            }

        hour = ts.hour if hasattr(ts, "hour") else 0
        dow  = ts.dayofweek if hasattr(ts, "dayofweek") else 0

        features: dict[str, float] = {
            # Regime
            "adx":              _safe(regime.get("adx", 0)),
            "atr_ratio":        _safe(regime.get("atr_ratio", 1.0)),
            "regime_trending":  1.0 if regime.get("regime") == "trending" else 0.0,
            "regime_ranging":   1.0 if regime.get("regime") == "ranging"  else 0.0,
            "regime_volatile":  1.0 if regime.get("regime") == "volatile" else 0.0,
            # Bias
            "bias_bullish":     1.0 if bias.get("direction") == "bullish" else 0.0,
            "bias_strength":    _safe(bias.get("strength", 0)),
            "bos_strength":     _safe(bias.get("bos_strength", bias.get("strength", 0))),
            "bars_since_bos":   _safe(bias.get("bars_since_bos", 0)),
            "weekly_bias_bullish": 1.0 if weekly.get("direction") == "bullish" else 0.0,
            # Zone
            "in_demand_zone":   1.0 if (zone and getattr(zone, "zone_type", "") == "demand") else 0.0,
            "in_supply_zone":   1.0 if (zone and getattr(zone, "zone_type", "") == "supply") else 0.0,
            "zone_strength":    _safe(getattr(zone, "strength", 0) if zone else 0),
            "zone_test_count":  _safe(getattr(zone, "test_count", 0) if zone else 0),
            "zone_top":         _safe(getattr(zone, "top", 0) if zone else 0),
            "zone_bottom":      _safe(getattr(zone, "bottom", 0) if zone else 0),
            # Entry
            "entry_confirmed":  1.0 if entry_i.get("passed") else 0.0,
            "sl_pips":          _safe(entry_i.get("sl_pips", 0)),
            "tp_pips":          _safe(entry_i.get("tp_pips", 0)),
            "rr_ratio":         _safe(entry_i.get("tp_pips", 0) / max(entry_i.get("sl_pips", 1), 1e-8)),
            "entry_price_norm": _safe(entry_i.get("entry_price", 0)),
            "sl_price_norm":    _safe(entry_i.get("sl_price", 0)),
            # Weekly
            "weekly_bos_strength":    _safe(weekly.get("bos_strength", 0)),
            "bars_since_weekly_bos":  _safe(weekly.get("bars_since_weekly_bos", 0)),
            "weekly_bullish":         1.0 if weekly.get("direction") == "bullish" else 0.0,
            "weekly_bearish":         1.0 if weekly.get("direction") == "bearish" else 0.0,
            # Spread
            "current_spread":  _safe(spread.get("current_spread", 0)),
            "spread_baseline": _safe(spread.get("baseline", 1)),
            "spread_ratio":    _safe(spread.get("current_spread", 0) / max(spread.get("baseline", 1), 1e-8)),
            # Time
            "hour_sin":      float(np.sin(2 * np.pi * hour / 24)),
            "hour_cos":      float(np.cos(2 * np.pi * hour / 24)),
            "day_sin":       float(np.sin(2 * np.pi * dow / 7)),
            "day_cos":       float(np.cos(2 * np.pi * dow / 7)),
            "session_london": 1.0 if 7 <= hour < 16 else 0.0,
        }

        features.update(_ohlc_features(htf_df, "htf"))
        features.update(_ohlc_features(ltf_df, "ltf"))

        # Guarantee exactly 50 features in FEATURE_NAMES order
        return {k: _safe(features.get(k, 0.0)) for k in FEATURE_NAMES}
