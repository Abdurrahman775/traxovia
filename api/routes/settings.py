"""
api/routes/settings.py — User settings read/update.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from database.connection import get_db, set_rls_user
from api.auth import get_current_user

router = APIRouter(tags=["settings"])


class SettingsPatch(BaseModel):
    base_risk_pct:    float | None = None
    is_paper_mode:    bool  | None = None
    max_trades_per_day: int | None = None


@router.get("/settings")
async def get_settings(user=Depends(get_current_user), db=Depends(get_db)):
    await set_rls_user(db, user["sub"])
    row = await db.fetchrow(
        """SELECT base_risk_pct, is_paper_mode, max_trades_per_day,
                  plan, email, weekly_confluence_enabled
           FROM users WHERE id=$1""",
        user["sub"],
    )
    return dict(row) if row else {}


@router.patch("/settings")
async def update_settings(
    body: SettingsPatch,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    await set_rls_user(db, user["sub"])
    updates, params, i = [], [], 1
    if body.base_risk_pct is not None:
        updates.append(f"base_risk_pct=${i}"); params.append(body.base_risk_pct); i += 1
    if body.is_paper_mode is not None:
        updates.append(f"is_paper_mode=${i}"); params.append(body.is_paper_mode); i += 1
    if body.max_trades_per_day is not None:
        updates.append(f"max_trades_per_day=${i}"); params.append(body.max_trades_per_day); i += 1
    if updates:
        params.append(user["sub"])
        await db.execute(
            f"UPDATE users SET {', '.join(updates)}, updated_at=NOW() WHERE id=${i}",
            *params,
        )
    return {"status": "updated"}
