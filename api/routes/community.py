"""
api/routes/community.py — Community channel stats and manual drops.
Admin-only (elite plan).
"""
from fastapi import APIRouter, Depends, HTTPException
from database.connection import get_db
from api.auth import get_current_user

router = APIRouter(prefix="/community", tags=["community"])


def _require_admin(user):
    if user["plan"] not in {"elite"}:
        raise HTTPException(403, "Admin access required")


@router.get("/stats")
async def community_stats(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    # Count users on community plan as channel members proxy
    members = await db.fetchval("SELECT COUNT(*) FROM users WHERE plan='community'") or 0
    signal_drops = await db.fetchval(
        "SELECT COUNT(*) FROM audit_log WHERE action='community_signal_drop'"
    ) or 0
    result_drops = await db.fetchval(
        "SELECT COUNT(*) FROM audit_log WHERE action='community_result_drop'"
    ) or 0
    # Conversion: community users who upgraded
    converted = await db.fetchval(
        "SELECT COUNT(*) FROM users WHERE plan != 'community' AND referred_by IS NOT NULL"
    ) or 0
    conversion_rate = round((converted / members * 100), 1) if members > 0 else 0.0
    return {
        "members": members,
        "signal_drops": signal_drops,
        "result_drops": result_drops,
        "conversion_rate": conversion_rate,
    }


@router.get("/drops")
async def list_drops(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    rows = await db.fetch(
        """SELECT t.id, t.pair, t.direction, t.pnl_r, t.exit_time AS created_at
           FROM trades t
           WHERE t.status = 'closed' AND t.pnl_r IS NOT NULL
           ORDER BY t.exit_time DESC LIMIT 20"""
    )
    return [
        {
            "id": str(r["id"]),
            "pair": r["pair"],
            "direction": (r["direction"] or "").upper(),
            "pnl_r": float(r["pnl_r"]),
            "created_at": r["created_at"].strftime("%b %d") if r["created_at"] else "—",
        }
        for r in rows
    ]


@router.post("/drop-signal")
async def drop_signal(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    # Get the latest pending signal to drop
    signal = await db.fetchrow(
        """SELECT id, pair, direction, entry_price, take_profit, ai_probability
           FROM trade_signals WHERE status='pending'
           ORDER BY created_at DESC LIMIT 1"""
    )
    if not signal:
        raise HTTPException(404, "No pending signal to drop")

    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        user["sub"], "community_signal_drop",
        f"Signal dropped: {signal['pair']} {signal['direction']}",
    )

    # Post to Telegram channel if configured
    try:
        from telegram.community_drops import post_result_drop
        import asyncio
        asyncio.create_task(post_result_drop(dict(signal), dict(signal)))
    except Exception:
        pass

    return {"status": "dropped", "pair": signal["pair"], "direction": signal["direction"]}


@router.post("/drop-result")
async def drop_result(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    trade = await db.fetchrow(
        """SELECT t.id, t.pair, t.direction, t.pnl_r, t.exit_time,
                  ts.regime, ts.ai_probability, ts.entry_price
           FROM trades t
           LEFT JOIN trade_signals ts ON ts.id = t.signal_id
           WHERE t.status='closed' AND t.pnl_r IS NOT NULL
           ORDER BY t.exit_time DESC LIMIT 1"""
    )
    if not trade:
        raise HTTPException(404, "No closed trade to drop")

    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        user["sub"], "community_result_drop",
        f"Result dropped: {trade['pair']} {float(trade['pnl_r']):+.2f}R",
    )

    try:
        from telegram.community_drops import post_result_drop
        import asyncio
        asyncio.create_task(post_result_drop(dict(trade), dict(trade)))
    except Exception:
        pass

    return {
        "status": "dropped",
        "pair": trade["pair"],
        "pnl_r": float(trade["pnl_r"]),
    }
