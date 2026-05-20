"""core/strategy_engine/news_filter.py — Skip trades around high-impact news events.

Fetches the ForexFactory economic calendar (free JSON endpoint) and blocks
trading within 60 minutes before or after any high-impact event for the
currencies involved in the symbol being traded.

Falls back to allowing the trade if the calendar cannot be fetched.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Cache calendar for the session so we don't hammer the API
_calendar_cache: list[dict] | None = None
_cache_fetched_at: datetime | None = None
_CACHE_TTL_HOURS = 4

_CURRENCIES: dict[str, list[str]] = {
    "USDJPY": ["USD", "JPY"],
    "XAUUSD": ["USD", "XAU"],
}

_BLOCK_MINUTES = 60  # block window before and after event


async def _fetch_calendar() -> list[dict]:
    global _calendar_cache, _cache_fetched_at

    now = datetime.now(timezone.utc)
    if (_calendar_cache is not None and _cache_fetched_at is not None
            and (now - _cache_fetched_at).total_seconds() < _CACHE_TTL_HOURS * 3600):
        return _calendar_cache

    try:
        import aiohttp
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    _calendar_cache   = data if isinstance(data, list) else []
                    _cache_fetched_at = now
                    return _calendar_cache
    except Exception as e:
        logger.debug("News filter: calendar fetch failed: %s", e)

    return _calendar_cache or []


async def check_news_window(symbol: str, dt: datetime | None = None) -> dict:
    """
    Returns {"passed": bool, "reason": str, "event": str|None}.
    dt defaults to now (UTC).
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    currencies = _CURRENCIES.get(symbol.upper(), ["USD"])
    block_window = timedelta(minutes=_BLOCK_MINUTES)

    try:
        events = await _fetch_calendar()
    except Exception:
        return {"passed": True, "reason": "calendar_unavailable", "event": None}

    for event in events:
        # Only care about high-impact events
        if event.get("impact", "").lower() not in ("high", "red"):
            continue

        currency = event.get("currency", "").upper()
        if currency not in currencies:
            continue

        # Parse event time
        date_str = event.get("date", "")
        time_str = event.get("time", "")
        try:
            if time_str:
                event_dt = datetime.strptime(
                    f"{date_str} {time_str}", "%Y-%m-%d %I:%M%p"
                ).replace(tzinfo=timezone.utc)
            else:
                continue
        except Exception:
            continue

        if abs((dt - event_dt).total_seconds()) <= block_window.total_seconds():
            return {
                "passed": False,
                "reason": "high_impact_news_window",
                "event":  f"{currency} {event.get('title', '')} @ {time_str}",
            }

    return {"passed": True, "reason": "no_news_conflict", "event": None}
