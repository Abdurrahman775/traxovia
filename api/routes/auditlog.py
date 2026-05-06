"""api/routes/auditlog.py — Read-only paginated audit log."""
from fastapi import APIRouter, Depends, Query
from database.connection import get_db, set_rls_user
from api.auth import get_current_user

router = APIRouter(prefix="/audit", tags=["audit"])

_EVENT_TYPES = [
    "admin_action", "ai_model", "authentication", "billing",
    "bridge_event", "mt5_binding", "risk_change", "signal_action",
]


@router.get("")
async def get_audit_log(
    user=Depends(get_current_user),
    db=Depends(get_db),
    page:      int        = Query(default=1,  ge=1),
    page_size: int        = Query(default=50, ge=1, le=100),
    action:    str | None = Query(default=None),
):
    await set_rls_user(db, user["sub"])
    offset = (page - 1) * page_size

    if action:
        rows = await db.fetch(
            """SELECT id, action, detail, ip_address, user_agent, created_at
               FROM audit_log WHERE user_id=$1::uuid AND action=$2
               ORDER BY created_at DESC LIMIT $3 OFFSET $4""",
            user["sub"], action, page_size, offset,
        )
        total = await db.fetchval(
            "SELECT COUNT(*) FROM audit_log WHERE user_id=$1::uuid AND action=$2",
            user["sub"], action,
        )
    else:
        rows = await db.fetch(
            """SELECT id, action, detail, ip_address, user_agent, created_at
               FROM audit_log WHERE user_id=$1::uuid
               ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
            user["sub"], page_size, offset,
        )
        total = await db.fetchval(
            "SELECT COUNT(*) FROM audit_log WHERE user_id=$1::uuid", user["sub"],
        )

    entries = []
    for r in rows:
        d = dict(r)
        ca = d.get("created_at")
        if ca is not None and hasattr(ca, "isoformat"):
            d["created_at"] = ca.isoformat()
        entries.append(d)

    return {
        "entries":     entries,
        "total":       total or 0,
        "page":        page,
        "page_size":   page_size,
        "event_types": _EVENT_TYPES,
    }
