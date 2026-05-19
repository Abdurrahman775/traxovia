"""core/strategy_engine/daily_bias_filter.py — Gate 0: Daily TF bias alignment.

Resamples H4 OHLC to Daily candles and checks whether the Daily BOS
direction matches the H4 bias. Only trades in the Daily trend direction
are allowed — filters out ~40% of counter-trend setups that look valid
on H4 but are fighting the higher timeframe.
"""
from __future__ import annotations

import pandas as pd

from core.structure_engine.bos_identifier import BOSIdentifier

_bos = BOSIdentifier(n=3)
_MAX_DAILY_BOS_AGE = 10  # Daily bars (~2 weeks)


def _resample_h4_to_daily(h4_df: pd.DataFrame) -> pd.DataFrame:
    """Resample H4 OHLC to Daily candles."""
    df = h4_df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")
    daily = df.resample("1D").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["open", "close"])
    daily = daily.reset_index().rename(columns={"time": "time"})
    return daily


_DAILY_EXEMPT = {"XAUUSD"}  # Gold moves on macro/dollar drivers, not price structure BOS


def check_daily_alignment(h4_df: pd.DataFrame, h4_bias_direction: str, symbol: str = "") -> dict:
    """
    Returns {"passed": bool, "reason": str, "daily_direction": str|None}.

    Passes when Daily BOS direction matches h4_bias_direction (or no
    Daily BOS exists within age limit — neutral, we give benefit of doubt).
    Fails when Daily BOS direction is opposite to h4_bias_direction.
    """
    if symbol.upper() in _DAILY_EXEMPT:
        return {"passed": True, "reason": "daily_alignment_exempt", "daily_direction": None}

    if h4_df is None or len(h4_df) < 30:
        return {"passed": True, "reason": "insufficient_data_for_daily", "daily_direction": None}

    try:
        daily = _resample_h4_to_daily(h4_df)
    except Exception:
        return {"passed": True, "reason": "resample_error", "daily_direction": None}

    if len(daily) < 10:
        return {"passed": True, "reason": "too_few_daily_bars", "daily_direction": None}

    bos_df   = _bos.identify(daily)
    last_idx = len(bos_df) - 1

    bull_pos = [i for i, v in enumerate(bos_df["bullish_bos"]) if v]
    bear_pos = [i for i, v in enumerate(bos_df["bearish_bos"]) if v]

    last_bull = bull_pos[-1] if bull_pos else -1
    last_bear = bear_pos[-1] if bear_pos else -1

    if last_bull == -1 and last_bear == -1:
        # No daily BOS — neutral, allow trade
        return {"passed": True, "reason": "no_daily_bos", "daily_direction": None}

    if last_bull >= last_bear:
        daily_dir  = "bullish"
        bars_since = last_idx - last_bull
    else:
        daily_dir  = "bearish"
        bars_since = last_idx - last_bear

    if bars_since > _MAX_DAILY_BOS_AGE:
        # Daily BOS too old — neutral
        return {"passed": True, "reason": "daily_bos_too_old", "daily_direction": daily_dir}

    if daily_dir != h4_bias_direction:
        return {
            "passed":          False,
            "reason":          "daily_bias_conflict",
            "daily_direction": daily_dir,
        }

    return {"passed": True, "reason": "daily_aligned", "daily_direction": daily_dir}
