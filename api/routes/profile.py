"""api/routes/profile.py — User profile read/update + password change."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from passlib.context import CryptContext

from database.connection import get_db, set_rls_user
from api.auth import get_current_user

router = APIRouter(prefix="/profile", tags=["profile"])
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


class ProfilePatch(BaseModel):
    display_name: str | None = None
    avatar_url:   str | None = None   # base64 data-URL or https URL


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password:     str


@router.get("")
async def get_profile(user=Depends(get_current_user), db=Depends(get_db)):
    await set_rls_user(db, user["sub"])
    row = await db.fetchrow(
        """SELECT email, plan, display_name, avatar_url, created_at
           FROM users WHERE id = $1""",
        user["sub"],
    )
    if not row:
        raise HTTPException(404, "User not found")
    d = dict(row)
    if d.get("created_at"):
        d["created_at"] = d["created_at"].isoformat()
    return d


@router.patch("")
async def update_profile(
    body: ProfilePatch,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    await set_rls_user(db, user["sub"])
    updates, params, i = [], [], 1

    if body.display_name is not None:
        display_name = body.display_name.strip()[:80]
        updates.append(f"display_name=${i}"); params.append(display_name); i += 1

    if body.avatar_url is not None:
        # Accept base64 data-URLs (max ~300 KB encoded) or plain https URLs
        if len(body.avatar_url) > 400_000:
            raise HTTPException(413, "Avatar too large (max ~300 KB)")
        updates.append(f"avatar_url=${i}"); params.append(body.avatar_url); i += 1

    if updates:
        params.append(user["sub"])
        await db.execute(
            f"UPDATE users SET {', '.join(updates)}, updated_at=NOW() WHERE id=${i}",
            *params,
        )
    return {"status": "updated"}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    await set_rls_user(db, user["sub"])
    row = await db.fetchrow(
        "SELECT password_hash FROM users WHERE id = $1", user["sub"]
    )
    if not row or not _pwd.verify(body.current_password, row["password_hash"]):
        raise HTTPException(400, "Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")

    new_hash = _pwd.hash(body.new_password)
    await db.execute(
        "UPDATE users SET password_hash=$1, updated_at=NOW() WHERE id=$2",
        new_hash, user["sub"],
    )
    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        user["sub"], "change_password", "Password changed",
    )
    return {"status": "password_changed"}
