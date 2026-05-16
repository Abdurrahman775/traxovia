"""api/routes/referral.py — Referral system."""
import ipaddress
import secrets
import os
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from database.connection import get_db, set_rls_user
from api.auth import get_current_user
from api.middleware.rate_limit import rate_limit

router = APIRouter(tags=["referral"])
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


def _same_subnet(ip1: str, ip2: str, prefix: int = 24) -> bool:
    try:
        net1 = ipaddress.ip_network(f"{ip1}/{prefix}", strict=False)
        return ipaddress.ip_address(ip2) in net1
    except ValueError:
        return False


@router.get("/referral/my-code")
async def get_my_referral_code(user=Depends(get_current_user), db=Depends(get_db)):
    user_id = user["sub"]
    code = await db.fetchval("SELECT referral_code FROM users WHERE id=$1", user_id)
    if not code:
        code = "TRADER-" + secrets.token_hex(3).upper()
        await set_rls_user(db, user_id)
        await db.execute("UPDATE users SET referral_code=$1 WHERE id=$2", code, user_id)
    from config import settings
    return {"referral_code": code, "referral_url": f"{settings.frontend_url}/?ref={code}"}


@router.post("/referral/apply")
async def apply_referral(
    request: Request,
    code: str,
    user=Depends(get_current_user),
    db=Depends(get_db),
    _=Depends(rate_limit(limit=5, window=60)),
):
    user_id = user["sub"]
    row = await db.fetchrow("SELECT referred_by FROM users WHERE id=$1", user_id)
    if row and row["referred_by"]:
        raise HTTPException(400, "Referral code already applied")

    referrer = await db.fetchrow(
        "SELECT id, signup_ip FROM users WHERE referral_code=$1", code
    )
    if not referrer:
        raise HTTPException(400, "Invalid referral code")
    if str(referrer["id"]) == user_id:
        raise HTTPException(400, "You cannot refer yourself")

    client_ip   = request.client.host if request.client else ""
    referrer_ip = str(referrer["signup_ip"]) if referrer["signup_ip"] else ""
    if referrer_ip and _same_subnet(client_ip, referrer_ip):
        raise HTTPException(400, "Referral not eligible — accounts appear to share a network")

    await set_rls_user(db, user_id)
    await db.execute("UPDATE users SET referred_by=$1 WHERE id=$2", referrer["id"], user_id)
    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        user_id, "billing", f"Referral code {code} applied",
    )
    return {"status": "applied", "message": "1 month free will be applied when you subscribe"}
