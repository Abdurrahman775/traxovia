"""
api/routes/bridge.py — Bridge status endpoint.
Reads from bridge_state table (written by bridge_watchdog).
"""
from fastapi import APIRouter, Depends
from database.connection import get_db
from api.auth import get_current_user

router = APIRouter(tags=["bridge"])


@router.get("/bridge/status")
async def bridge_status(user=Depends(get_current_user), db=Depends(get_db)):
    row = await db.fetchrow("SELECT * FROM bridge_state ORDER BY updated_at DESC LIMIT 1")
    if not row:
        return {
            "primary_url":     "http://127.0.0.1:8001",
            "standby_url":     "not configured",
            "active_url":      "http://127.0.0.1:8001",
            "primary_healthy": False,
            "standby_healthy": False,
            "trading_paused":  False,
            "failover_count":  0,
            "last_heartbeat":  None,
        }
    d = dict(row)
    d["primary_healthy"] = not d.get("trading_paused", False)
    d["standby_healthy"] = False
    if d.get("last_heartbeat"):
        d["last_heartbeat"] = d["last_heartbeat"].isoformat()
    if d.get("updated_at"):
        d["updated_at"] = d["updated_at"].isoformat()
    return d
