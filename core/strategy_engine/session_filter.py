"""core/strategy_engine/session_filter.py — Only trade during high-liquidity sessions.

Low-liquidity sessions (e.g. Asian session for EURUSD) produce choppy
fake-out moves that trigger SLs before the real move starts. This filter
restricts each pair to its highest-probability session window.

All times are UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone, time as dtime

# Session windows per pair: list of (start_hour_utc, end_hour_utc)
_SESSION_MAP: dict[str, list[tuple[int, int]]] = {
    "EURUSD": [(7, 17)],   # London + NY
    "GBPUSD": [(7, 17)],   # London + NY
    "USDJPY": [(0, 10)],   # Asian + London overlap
    "XAUUSD": [(7, 17)],   # London + NY (most volume)
    "AUDUSD": [(0, 10), (7, 17)],  # Asian + London
}

_DEFAULT_SESSIONS = [(7, 17)]


def is_valid_session(symbol: str, dt: datetime | None = None) -> dict:
    """
    Returns {"passed": bool, "reason": str, "hour_utc": int}.
    dt defaults to now (UTC) if not provided.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    hour = dt.hour
    windows = _SESSION_MAP.get(symbol.upper(), _DEFAULT_SESSIONS)

    for start, end in windows:
        if start <= hour < end:
            return {"passed": True,  "reason": "valid_session",   "hour_utc": hour}

    return {"passed": False, "reason": "outside_session", "hour_utc": hour}
