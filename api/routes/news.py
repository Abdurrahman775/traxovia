"""api/routes/news.py — Economic news calendar with plan-gated access."""
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import get_current_user
from api.middleware.rate_limit import rate_limit
from database.connection import get_db
from database.sync_connection import sync_fetchone

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/news", tags=["news"])

_PAID_PLANS = {"starter", "trader", "pro", "elite", "trial"}

# Country → forex pairs affected
_COUNTRY_PAIRS: dict[str, list[str]] = {
    "US":  ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"],
    "EU":  ["EURUSD"],
    "DE":  ["EURUSD"],
    "FR":  ["EURUSD"],
    "IT":  ["EURUSD"],
    "ES":  ["EURUSD"],
    "GB":  ["GBPUSD"],
    "UK":  ["GBPUSD"],
    "JP":  ["USDJPY"],
    "AU":  ["AUDUSD"],
    "NZ":  ["AUDUSD"],
    "CN":  ["AUDUSD", "XAUUSD"],
    "CA":  ["EURUSD", "GBPUSD"],
    "CH":  ["EURUSD"],
}

_IMPACT_ORDER  = {"high": 0, "medium": 1, "low": 2}
_VALID_IMPACTS = {"high", "medium", "low", "all"}
_VALID_PAIRS   = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"}


def _get_finnhub_key() -> str:
    row = sync_fetchone("SELECT finnhub_api_key FROM bot_config WHERE id=1")
    if row and row.get("finnhub_api_key"):
        return row["finnhub_api_key"]
    import os
    return os.getenv("FINNHUB_API_KEY", "")


def _event_id(event: dict) -> str:
    raw = f"{event.get('time','')}:{event.get('country','')}:{event.get('event','')}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _enrich(event: dict) -> dict:
    country = (event.get("country") or "").upper()
    impact  = (event.get("impact") or "low").lower()
    pairs   = _COUNTRY_PAIRS.get(country, [])

    time_str = event.get("time", "")
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        time_iso = dt.isoformat()
        time_label = dt.strftime("%H:%M UTC")
        minutes_away = int((dt - datetime.now(timezone.utc)).total_seconds() / 60)
    except Exception:
        time_iso = time_str
        time_label = time_str
        minutes_away = None

    return {
        "id":            _event_id(event),
        "time":          time_iso,
        "time_label":    time_label,
        "minutes_away":  minutes_away,
        "event":         event.get("event", ""),
        "country":       country,
        "impact":        impact,
        "estimate":      event.get("estimate") or "",
        "prev":          event.get("prev") or "",
        "actual":        event.get("actual") or "",
        "affected_pairs": pairs,
    }


@router.get("")
async def get_news(
    date:   Optional[str] = Query(None, description="YYYY-MM-DD, defaults to today UTC"),
    impact: Optional[str] = Query(None, description="high | medium | low | all"),
    pair:   Optional[str] = Query(None, description="Filter by affected pair e.g. EURUSD"),
    days:   int           = Query(1, ge=1, le=7, description="Number of days to fetch"),
    user=Depends(get_current_user),
    db=Depends(get_db),
    _=Depends(rate_limit(limit=20, window=60)),
):
    if user.get("plan", "community") not in _PAID_PLANS:
        raise HTTPException(403, "News feed requires Starter plan or above")

    # Validate impact
    if impact and impact.lower() not in _VALID_IMPACTS:
        raise HTTPException(400, f"Invalid impact value. Must be one of: {', '.join(sorted(_VALID_IMPACTS))}")

    # Validate pair
    if pair and pair.upper() not in _VALID_PAIRS:
        raise HTTPException(400, f"Invalid pair. Must be one of: {', '.join(sorted(_VALID_PAIRS))}")

    api_key = _get_finnhub_key()
    if not api_key or api_key == "your-finnhub-api-key":
        raise HTTPException(503, "News feed not configured — Finnhub API key missing")

    today = datetime.now(timezone.utc).date()
    try:
        from_dt = datetime.fromisoformat(date).date() if date else today
    except ValueError:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")
    to_dt = from_dt + timedelta(days=days - 1)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/calendar/economic",
                params={"from": str(from_dt), "to": str(to_dt), "token": api_key},
            )
        if resp.status_code == 401:
            raise HTTPException(503, "Finnhub API key invalid")
        if resp.status_code != 200:
            raise HTTPException(502, f"Finnhub returned {resp.status_code}")
        raw_events = resp.json().get("economicCalendar", [])
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("news: Finnhub fetch failed: %s", exc)
        raise HTTPException(502, "Failed to fetch news from Finnhub")

    events = [_enrich(e) for e in raw_events]

    # Filter by impact
    if impact and impact != "all":
        events = [e for e in events if e["impact"] == impact.lower()]

    # Filter by pair
    if pair:
        pair_upper = pair.upper()
        events = [e for e in events if pair_upper in e["affected_pairs"]]

    # Sort: by time ascending, high impact first within same minute
    events.sort(key=lambda e: (e["time"], _IMPACT_ORDER.get(e["impact"], 9)))

    high_count   = sum(1 for e in events if e["impact"] == "high")
    medium_count = sum(1 for e in events if e["impact"] == "medium")
    low_count    = sum(1 for e in events if e["impact"] == "low")

    return {
        "from":         str(from_dt),
        "to":           str(to_dt),
        "total":        len(events),
        "high_impact":  high_count,
        "medium_impact": medium_count,
        "low_impact":   low_count,
        "events":       events,
    }
