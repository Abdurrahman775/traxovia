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
# EURUSD: ICT killzones — London pre-open (4h), London open (7–10h), NY open (12–13h), NY mid (16h)
#   Diagnostic 2024–2026 (114 trades, no filter):
#     KEEP: 4h (75%WR +1.25R), 7h (80%WR +1.00R), 10h (67%WR +0.67R),
#           12h (70%WR +0.60R), 13h (100%WR +0.60R), 16h (50%WR +0.25R)
#     DROP: 5h/6h (pre-London fake-outs 17–37%WR), 17h (0%WR NY close),
#           1h/3h/14h/19h/21h (33% WR or lower)
#   Projected result with these windows: 46 trades, Avg R +0.391R (up from +0.063R)
_SESSION_MAP: dict[str, list[tuple[int, int]]] = {
    "USDJPY": [(0, 1), (3, 4), (5, 7), (8, 9)],
    "XAUUSD": [(7, 17)],   # London open → NY close
    "EURUSD": [(4, 5), (7, 11), (12, 14), (16, 17)],  # London pre + London + NY open + NY mid
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
