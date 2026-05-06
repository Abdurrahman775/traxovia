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
    return [dict(r) for r in rows]
