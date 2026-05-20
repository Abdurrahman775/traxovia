"""core/strategy_engine/session_filter.py — Only trade during high-liquidity sessions.

ICT killzone windows: entries only during peak institutional participation.
Outside these windows, smart money is absent and setups fail more often.

All times are UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Killzone windows per pair (start_hour_utc inclusive, end_hour_utc exclusive)
# USDJPY: Tokyo open + London overlap — 00:00–09:00 UTC
# XAUUSD: London open + NY session  — 07:00–17:00 UTC
_SESSION_MAP: dict[str, list[tuple[int, int]]] = {
    "USDJPY": [(0, 9)],    # Tokyo open → London overlap
    "XAUUSD": [(7, 17)],   # London open → NY close
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
