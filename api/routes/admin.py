"""
api/routes/admin.py — Admin-only stats, user list, and audit log.
Only accessible to users with plan='elite'.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from database.connection import get_db
from api.auth import get_current_user

router = APIRouter(tags=["admin"])


def _require_admin(user):
    if user["plan"] not in {"elite"}:
        raise HTTPException(403, "Admin access required")


@router.get("/admin/stats")
async def admin_stats(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    total_users  = await db.fetchval("SELECT COUNT(*) FROM users")
    new_week     = await db.fetchval("SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '7 days'")
    new_month    = await db.fetchval("SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '30 days'")
    plans        = await db.fetch("SELECT plan, COUNT(*) AS count FROM users GROUP BY plan ORDER BY count DESC")
    total_sigs   = await db.fetchval("SELECT COUNT(*) FROM trade_signals")
    approved     = await db.fetchval("SELECT COUNT(*) FROM trade_signals WHERE status='approved'")
    rejected     = await db.fetchval("SELECT COUNT(*) FROM trade_signals WHERE status='rejected'")
    pending      = await db.fetchval("SELECT COUNT(*) FROM trade_signals WHERE status='pending'")
    return {
        "users": {
            "total_users":    total_users,
            "admin_count":    0,
            "new_this_week":  new_week,
            "new_this_month": new_month,
        },
        "plan_distribution": [{"plan": r["plan"], "count": r["count"]} for r in plans],
        "signals": {
            "total_signals": total_sigs,
            "approved":      approved,
            "rejected":      rejected,
            "pending":       pending,
        },
    }


@router.get("/admin/users")
async def admin_users(
    limit: int = Query(100, le=500),
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    rows = await db.fetch(
        """SELECT id, email, plan, is_paper_mode, created_at, trial_expires_at
           FROM users ORDER BY created_at DESC LIMIT $1""",
        limit,
    )
    users = [dict(r) for r in rows]
    # Add is_admin field (elite plan = admin)
    for u in users:
        u["is_admin"] = u["plan"] == "elite"
        if u.get("created_at"):
            u["created_at"] = u["created_at"].isoformat()
        if u.get("trial_expires_at"):
            u["trial_expires_at"] = u["trial_expires_at"].isoformat()
    return {"total": len(users), "users": users}


@router.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    body: dict,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    if "plan" in body:
        await db.execute("UPDATE users SET plan=$1 WHERE id=$2", body["plan"], user_id)
    return {"status": "updated"}


@router.get("/admin/audit")
async def admin_audit(
    limit: int = Query(50, le=200),
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    rows = await db.fetch(
        """SELECT al.id, al.user_id, u.email, al.action, al.detail,
                  al.ip_address::text, al.created_at
           FROM audit_log al
           LEFT JOIN users u ON u.id = al.user_id
           ORDER BY al.created_at DESC LIMIT $1""",
        limit,
    )
    entries = []
    for r in rows:
        d = dict(r)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        entries.append(d)
    return {"entries": entries}
