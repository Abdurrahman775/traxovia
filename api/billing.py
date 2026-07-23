"""
api/billing.py — Paystack subscription management.

Endpoints
---------
POST /billing/webhook                  Paystack webhook receiver (verified by signature)
POST /billing/create-checkout-session  Redirect to Paystack Checkout for a plan upgrade
GET  /billing/subscription             Return the current user's plan
GET  /billing/plans                    Public plan catalogue with NGN pricing
GET  /billing/usage                    Monthly usage counters
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.auth import get_current_user
from config import settings
from database.connection import get_db, set_rls_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

VALID_PLANS = {"community", "starter", "trader", "pro", "elite"}

PLAN_PRICES: dict[str, str] = {
    "community": "₦0",
    "starter":   "₦14,900/mo",
    "trader":    "₦49,900/mo",
    "pro":       "₦99,900/mo",
    "elite":     "₦199,900/mo",
}


async def _get_payment_config(db) -> dict:
    row = await db.fetchrow("SELECT * FROM bot_config WHERE id=1")
    cfg = dict(row) if row else {}
    return {
        "paystack_secret_key": cfg.get("paystack_secret_key") or "",
        "paystack_public_key": cfg.get("paystack_public_key") or "",
    }


async def _get_paystack_plan_map(db) -> dict[str, str]:
    """Return {plan_id: paystack_plan_code} from plan_config.features."""
    rows = await db.fetch(
        "SELECT plan_id, features FROM plan_config WHERE is_active=TRUE AND plan_id != 'community'"
    )
    result = {}
    for r in rows:
        features = r["features"] if isinstance(r["features"], dict) else {}
        code = features.get("paystack_plan_code", "")
        if code:
            result[r["plan_id"]] = code
    return result


def _plan_rank(plan: str) -> int:
    return {"community": 0, "starter": 1, "trader": 2, "pro": 3, "elite": 4}.get(plan, -1)


async def _apply_plan_change(user_id: str, new_plan: str, source: str, db) -> None:
    # Validate plan exists in DB (dynamic — not a hardcoded set)
    if new_plan != "community":
        exists = await db.fetchval("SELECT 1 FROM plan_config WHERE plan_id=$1", new_plan)
        if not exists:
            raise ValueError(f"invalid plan '{new_plan}'")
    async with db.transaction():
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE id=$1::uuid FOR UPDATE", user_id
        )
        if not user or user["plan"] == new_plan:
            return
        old_plan = user["plan"]
        await db.execute(
            "UPDATE users SET plan=$1, updated_at=NOW() WHERE id=$2",
            new_plan, user["id"],
        )
        direction = "upgraded" if _plan_rank(new_plan) > _plan_rank(old_plan) else "downgraded"
        await set_rls_user(db, str(user["id"]))
        await db.execute(
            "INSERT INTO audit_log (user_id, action, detail) VALUES ($1,$2,$3)",
            user["id"],
            "plan_upgraded" if direction == "upgraded" else "plan_downgraded",
            f"Plan {direction} from {old_plan} to {new_plan} via {source}",
        )
    logger.info("billing: user %s %s → %s (%s)", user_id, old_plan, new_plan, source)


# ── Webhook ────────────────────────────────────────────────────────────────────

@router.post("/webhook", status_code=200)
async def paystack_webhook(request: Request, db=Depends(get_db)):
    payload = await request.body()
    cfg = await _get_payment_config(db)
    secret = cfg["paystack_secret_key"]

    sig = request.headers.get("x-paystack-signature", "")
    expected = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(400, "Invalid Paystack signature")

    event = json.loads(payload)
    event_type: str = event.get("event", "")
    data = event.get("data", {})

    try:
        if event_type == "subscription.create":
            email = data.get("customer", {}).get("email")
            plan_code = data.get("plan", {}).get("plan_code", "")
            plan_map = {v: k for k, v in (await _get_paystack_plan_map(db)).items()}
            plan = plan_map.get(plan_code)
            if email and plan:
                row = await db.fetchrow("SELECT id FROM users WHERE email=$1", email)
                if row:
                    await _apply_plan_change(str(row["id"]), plan, "paystack.subscription.create", db)

        elif event_type in ("subscription.disable", "subscription.not_renew"):
            email = data.get("customer", {}).get("email")
            if email:
                row = await db.fetchrow("SELECT id FROM users WHERE email=$1", email)
                if row:
                    await _apply_plan_change(str(row["id"]), "community", event_type, db)

        elif event_type == "charge.success":
            email = data.get("customer", {}).get("email")
            plan_code = data.get("plan", {}).get("plan_code", "") if data.get("plan") else ""
            plan_map = {v: k for k, v in (await _get_paystack_plan_map(db)).items()}
            plan = plan_map.get(plan_code)
            if email and plan:
                row = await db.fetchrow("SELECT id FROM users WHERE email=$1", email)
                if row:
                    await _apply_plan_change(str(row["id"]), plan, "paystack.charge.success", db)

    except Exception as exc:
        logger.exception("paystack webhook: error processing %s", event_type)
        raise HTTPException(500, "Webhook processing failed") from exc

    return {"status": "ok"}


# ── Checkout ───────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str


@router.post("/create-checkout-session")
async def create_checkout_session(
    body: CheckoutRequest,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    plan = body.plan.lower()

    cfg = await _get_payment_config(db)
    secret = cfg["paystack_secret_key"]
    if not secret:
        raise HTTPException(400, "Paystack secret key is not configured.")

    row = await db.fetchrow("SELECT email FROM users WHERE id=$1::uuid", user["sub"])
    email = row["email"] if row else ""

    payload: dict = {
        "email": email,
        "callback_url": f"{settings.frontend_url}/dashboard?checkout=success",
    }
    plan_map = await _get_paystack_plan_map(db)
    plan_code = plan_map.get(plan)
    if plan_code:
        payload["plan"] = plan_code
    else:
        # Fetch amount from plan_config
        plan_row = await db.fetchrow("SELECT price FROM plan_config WHERE plan_id=$1", plan)
        if not plan_row:
            raise HTTPException(400, f"Unknown plan '{plan}'")
        payload["amount"] = int(float(plan_row["price"]) * 100)  # kobo

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers={"Authorization": f"Bearer {secret}"},
        )
    if resp.status_code != 200:
        raise HTTPException(400, f"Paystack error: {resp.json().get('message', resp.text)}")

    return {"checkout_url": resp.json()["data"]["authorization_url"]}


# ── Subscription status ────────────────────────────────────────────────────────

@router.get("/subscription")
async def get_subscription(user: dict = Depends(get_current_user), db=Depends(get_db)):
    row = await db.fetchrow(
        "SELECT plan, trial_expires_at, is_paper_mode FROM users WHERE id=$1::uuid",
        user["sub"],
    )
    if not row:
        raise HTTPException(404, "User not found")
    return {
        "plan":             row["plan"],
        "price":            PLAN_PRICES.get(row["plan"], "unknown"),
        "is_paper_mode":    row["is_paper_mode"],
        "trial_expires_at": row["trial_expires_at"].isoformat() if row["trial_expires_at"] else None,
    }


# ── Plans catalogue ────────────────────────────────────────────────────────────

@router.get("/plans")
async def get_plans(db=Depends(get_db)):
    rows = await db.fetch(
        "SELECT plan_id, name, price, color, popular, sort_order, features "
        "FROM plan_config WHERE is_active=TRUE ORDER BY sort_order"
    )
    plans = []
    for r in rows:
        d = dict(r)
        d["price"] = float(d["price"])
        if isinstance(d.get("features"), str):
            try:
                d["features"] = json.loads(d["features"])
            except (ValueError, TypeError):
                d["features"] = {}
        plans.append(d)
    return {"currency": "NGN", "symbol": "₦", "plans": plans}


# ── Usage ──────────────────────────────────────────────────────────────────────

@router.get("/usage")
async def get_usage(user: dict = Depends(get_current_user), db=Depends(get_db)):
    await set_rls_user(db, user["sub"])
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    signals = await db.fetchval(
        "SELECT COUNT(*) FROM trade_signals WHERE user_id=$1 AND created_at>=$2",
        user["sub"], month_start,
    ) or 0
    trades = await db.fetchval(
        "SELECT COUNT(*) FROM trades WHERE user_id=$1 AND entry_time>=$2",
        user["sub"], month_start,
    ) or 0
    row = await db.fetchrow("SELECT mt5_accounts FROM users WHERE id=$1::uuid", user["sub"])
    mt5_raw = row["mt5_accounts"] if row else None
    if isinstance(mt5_raw, str):
        try:
            mt5_raw = json.loads(mt5_raw)
        except (ValueError, TypeError):
            mt5_raw = []
    return {
        "signals_generated": int(signals),
        "trades_executed":   int(trades),
        "api_calls":         0,
        "mt5_accounts":      len(mt5_raw) if isinstance(mt5_raw, list) else 0,
    }
