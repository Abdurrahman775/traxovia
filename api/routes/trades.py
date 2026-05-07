"""
api/routes/trades.py — Trade history endpoint.
"""
from fastapi import APIRouter, Depends, Query
from database.connection import get_db, set_rls_user
from api.auth import get_current_user

router = APIRouter(tags=["trades"])


@router.get("/trades")
async def list_trades(
    status: str | None = Query(None),
    limit:  int        = Query(100, le=500),
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    await set_rls_user(db, user["sub"])
    where = "WHERE user_id=$1"
    params = [user["sub"]]
    if status:
        where += " AND status=$2"
        params.append(status)
    rows = await db.fetch(
        f"""SELECT id, pair, direction, entry_price, exit_price, stop_loss,
                   take_profit, lot_size, pnl_r, pips, status, regime,
                   entry_time, exit_time, duration_hours, mt5_ticket, is_paper
            FROM trades {where}
            ORDER BY entry_time DESC LIMIT {limit}""",
        *params,
    )
    result = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"]) if d.get("id") else None
        for ts in ("entry_time", "exit_time"):
            if d.get(ts) and hasattr(d[ts], "isoformat"):
                d[ts] = d[ts].isoformat()
        for num in ("entry_price", "exit_price", "stop_loss", "take_profit", "lot_size", "pnl_r", "pips", "duration_hours"):
            if d.get(num) is not None:
                d[num] = float(d[num])
        result.append(d)
    return result
