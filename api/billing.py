"""
api/billing.py — Stripe subscription management.

Endpoints
---------
POST /billing/webhook                  Stripe webhook receiver (no auth — verified by signature)
POST /billing/create-checkout-session  Start a Stripe Checkout flow for a plan upgrade
POST /billing/customer-portal          Open the Stripe Billing Portal for self-service management
GET  /billing/subscription             Return the current user's plan and subscription status

Webhook events handled
----------------------
customer.subscription.created   → activate new plan
customer.subscription.updated   → apply plan change (upgrade / downgrade / reinstatement)
customer.subscription.deleted   → downgrade to community on cancellation / non-payment

Plan → price ID mapping is read from env at startup (STRIPE_PRICE_*).
Plan updates touch only the users table, which has no RLS, so no set_rls_user()
call is required for the UPDATE. set_rls_user() is still required before the
audit_log INSERT because audit_log does have RLS.

Phase 1 quality gate: trigger subscription.created via Stripe CLI and confirm
the user's plan column updates within 5 seconds.
"""

import json
import logging
from datetime import datetime, timezone

import httpx
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.auth import get_current_user
from config import settings
from database.connection import get_db, set_rls_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


# ── Dynamic payment config ─────────────────────────────────────────────────────

async def _get_payment_config(db) -> dict:
    """Read payment gateway config from DB; fall back to .env for each field."""
    row = await db.fetchrow("SELECT * FROM bot_config WHERE id=1")
    cfg = dict(row) if row else {}
    return {
        "gateway":               cfg.get("payment_gateway") or "stripe",
        "stripe_secret_key":     cfg.get("stripe_secret_key")     or settings.stripe_secret_key,
        "stripe_webhook_secret": cfg.get("stripe_webhook_secret") or settings.stripe_webhook_secret,
        "stripe_price_starter":  cfg.get("stripe_price_starter")  or settings.stripe_price_starter,
        "stripe_price_trader":   cfg.get("stripe_price_trader")   or settings.stripe_price_trader,
        "stripe_price_pro":      cfg.get("stripe_price_pro")      or settings.stripe_price_pro,
        "stripe_price_elite":    cfg.get("stripe_price_elite")    or settings.stripe_price_elite,
        "paystack_secret_key":   cfg.get("paystack_secret_key")   or "",
        "paystack_public_key":   cfg.get("paystack_public_key")   or "",
        "paystack_plan_starter": cfg.get("paystack_plan_starter") or "",
        "paystack_plan_trader":  cfg.get("paystack_plan_trader")  or "",
        "paystack_plan_pro":     cfg.get("paystack_plan_pro")     or "",
        "paystack_plan_elite":   cfg.get("paystack_plan_elite")   or "",
    }

# ── Plan definitions ───────────────────────────────────────────────────────────

# All valid plan names in the platform. "community" is the free / downgrade target.
VALID_PLANS = {"community", "starter", "trader", "pro", "elite"}

# Human-readable prices — used in audit log messages only.
PLAN_PRICES: dict[str, str] = {
    "community": "$0",
    "starter":   "$29/mo",
    "trader":    "$79/mo",
    "pro":       "$149/mo",
    "elite":     "$299/mo",
}

# Stripe subscription statuses that mean the subscription is effectively active.
_ACTIVE_STATUSES = {"active", "trialing"}


def _price_to_plan_map(cfg: dict) -> dict[str, str]:
    m: dict[str, str] = {}
    for plan in ("starter", "trader", "pro", "elite"):
        price_id = cfg.get(f"stripe_price_{plan}", "")
        if price_id:
            m[price_id] = plan
    return m


def _paystack_plan_map(cfg: dict) -> dict[str, str]:
    m: dict[str, str] = {}
    for plan in ("starter", "trader", "pro", "elite"):
        code = cfg.get(f"paystack_plan_{plan}", "")
        if code:
            m[plan] = code
    return m


def _plan_from_subscription(sub: stripe.Subscription, cfg: dict) -> str | None:
    price_map = _price_to_plan_map(cfg)
    try:
        price_id = sub["items"]["data"][0]["price"]["id"]
        return price_map.get(price_id)
    except (KeyError, IndexError):
        return None


# ── Internal helpers ───────────────────────────────────────────────────────────

async def _get_or_create_stripe_customer(user: dict, db) -> str:
    """
    Return the user's Stripe customer ID, creating a new Customer if needed.
    Stores the ID back to users table on creation.
    """
    row = await db.fetchrow(
        "SELECT id, email, stripe_customer_id FROM users WHERE id = $1::uuid",
        user["sub"],
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if row["stripe_customer_id"]:
        return row["stripe_customer_id"]

    # Create a new Stripe customer linked to this account.
    customer = stripe.Customer.create(
        email=row["email"],
        metadata={"user_id": str(row["id"])},
    )
    await db.execute(
        "UPDATE users SET stripe_customer_id = $1 WHERE id = $2",
        customer["id"], row["id"],
    )
    return customer["id"]


async def _apply_plan_change(
    customer_id: str,
    new_plan: str,
    event_type: str,
    db,
) -> None:
    """
    Update the user's plan in the DB and write an audit log entry.
    Called by all three webhook handlers so the logic lives in one place.
    """
    user = await db.fetchrow(
        "SELECT id, plan FROM users WHERE stripe_customer_id = $1",
        customer_id,
    )
    if not user:
        # Customer exists in Stripe but not in our DB — skip silently.
        # This can happen with test customers or accounts deleted by an admin.
        logger.warning("stripe webhook: no user found for customer %s", customer_id)
        return

    old_plan = user["plan"]
    if old_plan == new_plan:
        return  # No change — idempotent update, nothing to do.

    await db.execute(
        "UPDATE users SET plan = $1, updated_at = NOW() WHERE id = $2",
        new_plan, user["id"],
    )

    direction = "upgraded" if _plan_rank(new_plan) > _plan_rank(old_plan) else "downgraded"
    detail = (
        f"Plan {direction} from {old_plan} ({PLAN_PRICES.get(old_plan, '?')}) "
        f"to {new_plan} ({PLAN_PRICES.get(new_plan, '?')}) "
        f"via Stripe event {event_type}"
    )

    await set_rls_user(db, str(user["id"]))
    await db.execute(
        """
        INSERT INTO audit_log (user_id, action, detail)
        VALUES ($1, $2, $3)
        """,
        user["id"],
        "plan_upgraded" if direction == "upgraded" else "plan_downgraded",
        detail,
    )

    logger.info(
        "billing: user %s %s — %s → %s (event: %s)",
        user["id"], direction, old_plan, new_plan, event_type,
    )


def _plan_rank(plan: str) -> int:
    """Numeric rank so upgrade vs downgrade direction can be determined."""
    return {"community": 0, "starter": 1, "trader": 2, "pro": 3, "elite": 4}.get(plan, -1)


# ── Webhook endpoint ───────────────────────────────────────────────────────────

@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Receive and process Stripe webhook events",
    # No auth dependency — Stripe does not send a JWT.
    # Security is provided by signature verification below.
)
async def stripe_webhook(request: Request, db=Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")
    cfg = await _get_payment_config(db)
    stripe.api_key = cfg["stripe_secret_key"]

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, cfg["stripe_webhook_secret"]
        )
    except stripe.error.SignatureVerificationError:
        logger.warning("stripe webhook: invalid signature")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Stripe signature")
    except Exception as exc:
        logger.warning("stripe webhook: malformed payload — %s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed webhook payload")

    event_type: str = event["type"]
    sub: stripe.Subscription = event["data"]["object"]

    try:
        if event_type == "customer.subscription.created":
            await _handle_subscription_created(sub, db, cfg)

        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(sub, db, cfg)

        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(sub, db)

        # All other event types are acknowledged but not processed.

    except Exception as exc:
        # Return 500 so Stripe retries — do not swallow DB errors silently.
        logger.exception("stripe webhook: unhandled error processing %s", event_type)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Webhook processing failed") from exc

    return {"status": "ok", "event": event_type}


# ── Webhook sub-handlers ───────────────────────────────────────────────────────

async def _handle_subscription_created(sub: stripe.Subscription, db, cfg: dict) -> None:
    """
    New subscription created.
    Only activate the plan if the subscription status is active or trialing.
    A `status=incomplete` means payment hasn't cleared yet — do not grant access.

    Note (Correction 2.5): payment method fingerprint fraud check for referrals
    is applied in api/routes/referral.py at reward-issuance time, not here.
    """
    if sub["status"] not in _ACTIVE_STATUSES:
        logger.info(
            "subscription.created with status=%s — deferring plan activation",
            sub["status"],
        )
        return

    plan = _plan_from_subscription(sub, cfg)
    if not plan:
        logger.warning("subscription.created: unrecognised price ID in subscription %s", sub["id"])
        return

    await _apply_plan_change(sub["customer"], plan, "customer.subscription.created", db)


async def _handle_subscription_updated(sub: stripe.Subscription, db, cfg: dict) -> None:
    """
    Subscription changed — covers upgrades, downgrades, and reinstatements
    after a failed-payment recovery.

    If the new status is not active/trialing, treat it as a cancellation and
    drop to community so access is revoked promptly (e.g. payment_failed →
    past_due → access removed before Stripe hard-cancels after grace period).
    """
    if sub["status"] not in _ACTIVE_STATUSES:
        await _apply_plan_change(
            sub["customer"], "community", "customer.subscription.updated", db
        )
        return

    plan = _plan_from_subscription(sub, cfg)
    if not plan:
        logger.warning("subscription.updated: unrecognised price ID in subscription %s", sub["id"])
        return

    await _apply_plan_change(sub["customer"], plan, "customer.subscription.updated", db)


async def _handle_subscription_deleted(sub: stripe.Subscription, db) -> None:
    """
    Subscription cancelled or permanently failed.
    Downgrade to community — revoke all paid features immediately.
    is_paper_mode is left unchanged here; trial expiry (expire_trials Celery
    task) handles that flag for trial cancellations.
    """
    await _apply_plan_change(
        sub["customer"], "community", "customer.subscription.deleted", db
    )


# ── Checkout session ───────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str


@router.post(
    "/create-checkout-session",
    summary="Create a Stripe Checkout session for a plan upgrade",
)
async def create_checkout_session(
    body: CheckoutRequest,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    cfg     = await _get_payment_config(db)
    gateway = cfg["gateway"]
    plan    = body.plan.lower()

    if gateway == "paystack":
        secret = cfg["paystack_secret_key"]
        if not secret:
            raise HTTPException(400, "Paystack secret key is not configured.")
        plan_code = _paystack_plan_map(cfg).get(plan)
        row = await db.fetchrow("SELECT email FROM users WHERE id=$1::uuid", user["sub"])
        email = row["email"] if row else ""
        payload: dict = {"email": email, "callback_url": f"{settings.frontend_url}/billing?checkout=success"}
        if plan_code:
            payload["plan"] = plan_code
        else:
            plan_prices = {"starter": 2900, "trader": 7900, "pro": 14900, "elite": 29900}
            payload["amount"] = plan_prices.get(plan, 2900)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.paystack.co/transaction/initialize",
                json=payload,
                headers={"Authorization": f"Bearer {secret}"},
            )
        if resp.status_code != 200:
            raise HTTPException(400, f"Paystack error: {resp.json().get('message', resp.text)}")
        data = resp.json()
        return {"checkout_url": data["data"]["authorization_url"]}

    # Default: Stripe
    stripe.api_key = cfg["stripe_secret_key"]
    price_map      = _price_to_plan_map(cfg)
    plan_to_price  = {v: k for k, v in price_map.items()}

    if plan not in plan_to_price:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown plan '{plan}'. Valid paid plans: starter, trader, pro, elite",
        )

    customer_id = await _get_or_create_stripe_customer(user, db)
    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": plan_to_price[plan], "quantity": 1}],
        success_url=f"{settings.frontend_url}/billing?checkout=success",
        cancel_url=f"{settings.frontend_url}/billing?checkout=cancelled",
        metadata={"user_id": user["sub"], "plan": plan},
    )
    return {"checkout_url": session["url"]}


# ── Customer portal ────────────────────────────────────────────────────────────

@router.post(
    "/customer-portal",
    summary="Open the Stripe Billing Portal for subscription self-management",
)
async def customer_portal(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    cfg = await _get_payment_config(db)
    stripe.api_key = cfg["stripe_secret_key"]

    row = await db.fetchrow(
        "SELECT stripe_customer_id FROM users WHERE id = $1::uuid", user["sub"]
    )
    if not row or not row["stripe_customer_id"]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No active Stripe subscription found",
        )

    session = stripe.billing_portal.Session.create(
        customer=row["stripe_customer_id"],
        return_url=f"{settings.frontend_url}/billing",
    )
    return {"portal_url": session["url"]}


# ── Subscription status ────────────────────────────────────────────────────────

@router.get(
    "/subscription",
    summary="Return the current user's plan and Stripe subscription status",
)
async def get_subscription(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    row = await db.fetchrow(
        "SELECT plan, stripe_customer_id, trial_expires_at, is_paper_mode FROM users WHERE id = $1::uuid",
        user["sub"],
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    result = {
        "plan":             row["plan"],
        "price":            PLAN_PRICES.get(row["plan"], "unknown"),
        "is_paper_mode":    row["is_paper_mode"],
        "trial_expires_at": row["trial_expires_at"].isoformat() if row["trial_expires_at"] else None,
    }

    # Optionally enrich with live Stripe subscription data if customer exists.
    if row["stripe_customer_id"]:
        try:
            cfg = await _get_payment_config(db)
            stripe.api_key = cfg["stripe_secret_key"]
            subs = stripe.Subscription.list(
                customer=row["stripe_customer_id"],
                status="active",
                limit=1,
            )
            if subs.data:
                live = subs.data[0]
                result["stripe_status"]       = live["status"]
                result["current_period_end"]  = live["current_period_end"]
                result["cancel_at_period_end"] = live["cancel_at_period_end"]
        except stripe.error.StripeError as exc:
            # Non-fatal: return DB plan even if Stripe API is unreachable.
            logger.warning("billing: Stripe API error fetching subscription: %s", exc)

    return result


# ── Public plan catalogue ──────────────────────────────────────────────────────

@router.get(
    "/plans",
    summary="Return all active plan definitions (prices + features)",
)
async def get_plans(db=Depends(get_db)):
    rows = await db.fetch(
        "SELECT plan_id, name, price, color, popular, sort_order, features "
        "FROM plan_config WHERE is_active = TRUE ORDER BY sort_order"
    )
    result = []
    for r in rows:
        d = dict(r)
        d["price"] = float(d["price"])
        if isinstance(d.get("features"), str):
            try:
                d["features"] = json.loads(d["features"])
            except (ValueError, TypeError):
                d["features"] = {}
        result.append(d)
    return result


# ── Usage stats ────────────────────────────────────────────────────────────────

@router.get(
    "/usage",
    summary="Return the current user's monthly usage counters",
)
async def get_usage(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    await set_rls_user(db, user["sub"])
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )

    signals_generated = await db.fetchval(
        "SELECT COUNT(*) FROM trade_signals WHERE user_id=$1 AND created_at >= $2",
        user["sub"], month_start,
    ) or 0

    trades_executed = await db.fetchval(
        "SELECT COUNT(*) FROM trades WHERE user_id=$1 AND entry_time >= $2",
        user["sub"], month_start,
    ) or 0

    row = await db.fetchrow(
        "SELECT mt5_accounts FROM users WHERE id=$1::uuid", user["sub"]
    )
    mt5_raw = row["mt5_accounts"] if row else None
    if isinstance(mt5_raw, str):
        try:
            mt5_raw = json.loads(mt5_raw)
        except (ValueError, TypeError):
            mt5_raw = []
    mt5_count = len(mt5_raw) if isinstance(mt5_raw, list) else 0

    return {
        "signals_generated": int(signals_generated),
        "trades_executed":   int(trades_executed),
        "api_calls":         0,
        "mt5_accounts":      mt5_count,
    }


# ── Invoice history ────────────────────────────────────────────────────────────

@router.get(
    "/invoices",
    summary="Return the last 12 Stripe invoices for the current user",
)
async def get_invoices(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    row = await db.fetchrow(
        "SELECT stripe_customer_id FROM users WHERE id=$1::uuid", user["sub"]
    )
    if not row or not row["stripe_customer_id"]:
        return []

    try:
        invoices = stripe.Invoice.list(
            customer=row["stripe_customer_id"],
            limit=12,
        )
    except stripe.error.StripeError as exc:
        logger.warning("billing: Stripe invoice list error: %s", exc)
        return []

    price_to_plan = {v: k for k, v in _price_to_plan_map().items()}

    result = []
    for inv in invoices.data:
        # Derive plan name from first line item price ID
        plan_name = "—"
        try:
            price_id = inv["lines"]["data"][0]["price"]["id"]
            plan_name = price_to_plan.get(price_id, plan_name)
        except (KeyError, IndexError):
            pass

        result.append({
            "id":     inv["id"],
            "date":   datetime.fromtimestamp(inv["created"], tz=timezone.utc)
                      .strftime("%b %d, %Y"),
            "plan":   plan_name,
            "amount": f"${inv['amount_paid'] / 100:.2f}",
            "status": inv["status"].upper(),
            "pdf":    inv.get("invoice_pdf"),
        })
    return result
