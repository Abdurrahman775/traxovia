"""core/strategy_engine/session_filter.py — Only trade during high-liquidity sessions.

ICT killzone windows: entries only during peak institutional participation.
Outside these windows, smart money is absent and setups fail more often.

All times are UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Killzone windows per pair (start_hour_utc inclusive, end_hour_utc exclusive)
# USDJPY: 4 precise killzone windows — hours 1,2,4,7 removed after diagnostic
#   0h = Tokyo open (27.5% WR)
#   3h, 5h, 6h = mid-Tokyo active (33% WR each)
#   8h = London open (53% WR — best hour)
#   Removed: 1h/2h (Asian dead zone), 4h (16.7% WR), 7h (0% — pre-London stop hunt)
# XAUUSD: London open + NY session  — 07:00–17:00 UTC
_SESSION_MAP: dict[str, list[tuple[int, int]]] = {
    "USDJPY": [(0, 1), (3, 4), (5, 7), (8, 9)],
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
