"""api/routes/analytics.py — Performance analytics from materialized views."""
from fastapi import APIRouter, Depends
from database.connection import get_db, set_rls_user
from api.auth import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])

_PAID_PLANS = {"starter", "trader", "pro", "elite", "trial"}


def _require_paid(user):
    if user.get("plan", "community") not in _PAID_PLANS:
        from fastapi import HTTPException
        raise HTTPException(403, "Analytics requires Starter plan or above")


@router.get("/summary")
async def analytics_summary(user=Depends(get_current_user), db=Depends(get_db)):
    _require_paid(user)
    await set_rls_user(db, user["sub"])
    total = await db.fetchval("SELECT COUNT(*) FROM trades WHERE user_id=$1 AND status='closed'", user["sub"]) or 0
    # pnl_r >= 0 counts both wins (3R) and break-even trades (SL→BE → 0R) as wins,
    # matching the backtest methodology where BE = no loss = trade managed correctly
    wins  = await db.fetchval("SELECT COUNT(*) FROM trades WHERE user_id=$1 AND status='closed' AND pnl_r >= 0", user["sub"]) or 0
    net   = await db.fetchval("SELECT COALESCE(SUM(pnl_r),0) FROM trades WHERE user_id=$1 AND status='closed'", user["sub"]) or 0
    win_rate = round(wins / total * 100, 1) if total > 0 else 0
    return {
        "total_trades": total,
        "win_rate": win_rate,
        "net_pnl_r": round(float(net), 2),
    }


@router.get("/by-pair")
async def analytics_by_pair(user=Depends(get_current_user), db=Depends(get_db)):
    await set_rls_user(db, user["sub"])
    rows = await db.fetch(
        """SELECT pair,
                  COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE pnl_r >= 0) AS wins,
                  COALESCE(SUM(pnl_r), 0) AS net_r
           FROM trades WHERE user_id=$1 AND status='closed'
           GROUP BY pair ORDER BY net_r DESC""",
        user["sub"],
    )
    return [
        {
            "pair": r["pair"],
            "total": r["total"],
            "win_rate": round(r["wins"] / r["total"] * 100, 1) if r["total"] > 0 else 0,
            "net_r": round(float(r["net_r"]), 2),
        }
        for r in rows
    ]


@router.get("/by-regime")
async def analytics_by_regime(user=Depends(get_current_user), db=Depends(get_db)):
    await set_rls_user(db, user["sub"])
    rows = await db.fetch(
        """SELECT regime,
                  COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE pnl_r >= 0) AS wins,
                  COALESCE(SUM(pnl_r), 0) AS net_r
           FROM trades WHERE user_id=$1 AND status='closed' AND regime IS NOT NULL
           GROUP BY regime""",
        user["sub"],
    )
    return [
        {
            "regime": r["regime"],
            "total": r["total"],
            "win_rate": round(r["wins"] / r["total"] * 100, 1) if r["total"] > 0 else 0,
            "net_r": round(float(r["net_r"]), 2),
        }
        for r in rows
    ]


@router.get("/performance")
async def analytics_performance(user=Depends(get_current_user), db=Depends(get_db)):
    """Uses mv_rolling_performance materialized view for fast reads."""
    _require_paid(user)
    await set_rls_user(db, user["sub"])
    row = await db.fetchrow(
        """SELECT win_rate_pct, net_r, total_trades
           FROM mv_rolling_performance
           WHERE user_id = $1::uuid""",
        user["sub"],
    )
    if not row:
        return {"win_rate": 0.0, "net_pnl_r": 0.0, "total_trades": 0}
    return {
        "win_rate":     float(row["win_rate_pct"] or 0),
        "net_pnl_r":    float(row["net_r"] or 0),
        "total_trades": int(row["total_trades"] or 0),
    }
