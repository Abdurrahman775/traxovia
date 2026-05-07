"""
api/routes/bridge.py — Bridge status endpoint.
Reads from bridge_state table (written by bridge_watchdog).
"""
from fastapi import APIRouter, Depends
from database.connection import get_db
from api.auth import get_current_user

router = APIRouter(tags=["bridge"])


_FALLBACK = {
    "primary_url":     "http://127.0.0.1:8001",
    "standby_url":     "not configured",
    "active_url":      "http://127.0.0.1:8001",
    "primary_healthy": True,
    "standby_healthy": False,
    "trading_paused":  False,
    "failover_count":  0,
    "last_heartbeat":  None,
    "source":          "fallback",
}

STALE_THRESHOLD_SECS = 180  # heartbeat older than 3 min → consider unhealthy


@router.get("/bridge/status")
async def bridge_status(user=Depends(get_current_user), db=Depends(get_db)):
    try:
        row = await db.fetchrow("SELECT * FROM bridge_state ORDER BY updated_at DESC LIMIT 1")
    except Exception:
        return _FALLBACK

    if not row:
        return _FALLBACK

    from datetime import datetime, timezone
    d = dict(row)

    # Derive primary_healthy from heartbeat recency, not just trading_paused flag
    hb = d.get("last_heartbeat")
    if hb is None:
        primary_healthy = False
    else:
        age_secs = (datetime.now(timezone.utc) - hb.replace(tzinfo=timezone.utc) if hb.tzinfo is None else datetime.now(timezone.utc) - hb).total_seconds()
        primary_healthy = age_secs <= STALE_THRESHOLD_SECS and not d.get("trading_paused", False)

    d["primary_healthy"] = primary_healthy
    d["standby_healthy"] = False
    d["source"] = "db"

    if d.get("last_heartbeat"):
        d["last_heartbeat"] = d["last_heartbeat"].isoformat()
    if d.get("updated_at"):
        d["updated_at"] = d["updated_at"].isoformat()
    if d.get("offline_since"):
        d["offline_since"] = d["offline_since"].isoformat()
    return d
