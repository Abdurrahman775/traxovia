"""api/routes/signals.py — Trade signals for the authenticated user."""
from fastapi import APIRouter, Depends, HTTPException, Query
from database.connection import get_db, set_rls_user
from api.auth import get_current_user

router = APIRouter(prefix="/signals", tags=["signals"])

_PAID_PLANS    = {"starter", "trader", "pro", "elite", "trial"}
_APPROVE_PLANS = {"trader", "pro", "elite"}


def _require_paid(user):
    if user.get("plan", "community") not in _PAID_PLANS:
        raise HTTPException(403, "Signals require Starter plan or above")


@router.get("")
async def list_signals(
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_paid(user)
    await set_rls_user(db, user["sub"])
    if status:
        rows = await db.fetch(
            """SELECT id, pair, direction, entry_price, stop_loss, take_profit,
                      regime, regime_adx, ai_probability, shap_values, reasoning,
                      status, triggered_at, created_at
               FROM trade_signals WHERE user_id=$1 AND status=$2
               ORDER BY created_at DESC LIMIT $3""",
            user["sub"], status, limit,
        )
    else:
        rows = await db.fetch(
            """SELECT id, pair, direction, entry_price, stop_loss, take_profit,
                      regime, regime_adx, ai_probability, shap_values, reasoning,
                      status, triggered_at, created_at
               FROM trade_signals WHERE user_id=$1
               ORDER BY created_at DESC LIMIT $2""",
            user["sub"], limit,
        )
    result = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        if d.get("triggered_at"): d["triggered_at"] = d["triggered_at"].isoformat()
        if d.get("created_at"):   d["created_at"]   = d["created_at"].isoformat()
        result.append(d)
    return result


@router.post("/{signal_id}/approve")
async def approve_signal(
    signal_id: str,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    if user.get("plan", "community") not in _APPROVE_PLANS:
        raise HTTPException(403, "Signal approval requires Trader plan or above")
    await set_rls_user(db, user["sub"])
    await db.execute(
        "UPDATE trade_signals SET status='approved' WHERE id=$1 AND user_id=$2",
        signal_id, user["sub"],
    )
    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        user["sub"], "signal_action", f"Signal {signal_id} approved",
    )
    return {"status": "approved"}


@router.patch("/{signal_id}")
async def update_signal(
    signal_id: str,
    body: dict,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_paid(user)
    new_status = body.get("status")
    if new_status not in {"approved", "rejected"}:
        raise HTTPException(400, "status must be 'approved' or 'rejected'")
    if new_status == "approved" and user.get("plan", "community") not in _APPROVE_PLANS:
        raise HTTPException(403, "Signal approval requires Trader plan or above")
    await set_rls_user(db, user["sub"])
    await db.execute(
        "UPDATE trade_signals SET status=$1 WHERE id=$2 AND user_id=$3",
        new_status, signal_id, user["sub"],
    )
    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        user["sub"], "signal_action", f"Signal {signal_id} {new_status}",
    )
    return {"status": new_status}
