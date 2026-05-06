"""api/routes/trial.py — 14-day free trial activation."""
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from database.connection import get_db, set_rls_user
from api.auth import get_current_user

router = APIRouter(prefix="/trial", tags=["trial"])


@router.post("/start")
async def start_trial(user=Depends(get_current_user), db=Depends(get_db)):
    await set_rls_user(db, user["sub"])
    # Plan comes from JWT; check trial_expires_at from DB
    if user.get("plan", "community") not in {"community", "trial"}:
        raise HTTPException(400, "Trial only available on community plan")
    row = await db.fetchrow("SELECT trial_expires_at FROM users WHERE id=$1", user["sub"])
    if row and row["trial_expires_at"] and row["trial_expires_at"] > datetime.now(timezone.utc):
        raise HTTPException(400, "Trial already active")

    expires = datetime.now(timezone.utc) + timedelta(days=14)
    await db.execute(
        "UPDATE users SET plan='trial', trial_expires_at=$1, is_paper_mode=TRUE WHERE id=$2",
        expires, user["sub"],
    )
    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        user["sub"], "billing", "14-day trial started",
    )
    return {"status": "trial_started", "paper_mode": True, "expires_at": expires.isoformat()}


@router.get("/status")
async def trial_status(user=Depends(get_current_user), db=Depends(get_db)):
    await set_rls_user(db, user["sub"])
    row = await db.fetchrow("SELECT plan, trial_expires_at FROM users WHERE id=$1", user["sub"])
    if not row:
        raise HTTPException(404, "User not found")
    active = (
        row["plan"] == "trial"
        and row["trial_expires_at"]
        and row["trial_expires_at"] > datetime.now(timezone.utc)
    )
    return {
        "plan": row["plan"],
        "trial_active": active,
        "trial_expires_at": row["trial_expires_at"].isoformat() if row["trial_expires_at"] else None,
    }
