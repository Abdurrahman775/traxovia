"""
api/routes/referral.py — Referral System
CORRECTIONS APPLIED:
  [FIX-5] PRD Section 11.2 required fraud prevention but the original code had none.
          Added:
            (a) Same /24 IP subnet check — voids referral if referrer + referred
                share the same /24 subnet at signup.
            (b) Stripe payment method fingerprint check — voids reward if both
                accounts use the same card (checked on subscription.created webhook).
            (c) Rate limiting on /referral/apply — 5 requests/minute per IP
                (requires slowapi middleware installed at app level).
            (d) 24-hour cooldown after a failed referral attempt.
"""

import os
import ipaddress
import secrets
from datetime import datetime, timedelta

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from database.connection import get_db
from api.auth import get_current_user

router  = Router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')


# ─── HELPERS ──────────────────────────────────────────────────────

def _same_subnet(ip1: str, ip2: str, prefix: int = 24) -> bool:
    """Returns True if two IPs share the same /24 subnet."""
    try:
        net1 = ipaddress.ip_network(f'{ip1}/{prefix}', strict=False)
        return ipaddress.ip_address(ip2) in net1
    except ValueError:
        return False  # malformed IP — fail open (non-fatal)


async def _get_stripe_card_fingerprint(stripe_customer_id: str) -> str | None:
    """Returns the fingerprint of the default payment method, or None."""
    try:
        customer = stripe.Customer.retrieve(
            stripe_customer_id,
            expand=['default_source'],
        )
        src = customer.get('default_source')
        if src and hasattr(src, 'fingerprint'):
            return src['fingerprint']
        # Also check payment_methods
        pms = stripe.PaymentMethod.list(customer=stripe_customer_id, type='card')
        if pms and pms.data:
            return pms.data[0].card.fingerprint
    except Exception:
        pass
    return None


# ─── ROUTES ───────────────────────────────────────────────────────

@router.get('/referral/my-code')
async def get_my_referral_code(
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Returns the current user's referral code, generating one if needed."""
    code = await db.fetchval(
        'SELECT referral_code FROM users WHERE id=$1', user['id']
    )
    if not code:
        code = 'TRADER-' + secrets.token_hex(3).upper()
        await db.execute(
            'UPDATE users SET referral_code=$1 WHERE id=$2', code, user['id']
        )
    return {'referral_code': code, 'referral_url': f'https://tradingai.com/?ref={code}'}


@router.post('/referral/apply')
@limiter.limit('5/minute')  # FIX-5c: rate limit — prevent code enumeration
async def apply_referral(
    request: Request,
    code: str,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Apply a referral code at signup.
    Performs IP subnet fraud check before applying any reward.
    """
    # ── Already has a referrer ────────────────────────────────────
    if user.get('referred_by'):
        raise HTTPException(400, 'Referral code already applied to this account')

    # ── FIX-5d: 24-hour cooldown after failed attempt ─────────────
    last_fail = await db.fetchval(
        """SELECT MAX(created_at) FROM audit_log
           WHERE user_id=$1 AND action='referral_failed'""",
        user['id'],
    )
    if last_fail and (datetime.utcnow() - last_fail).total_seconds() < 86400:
        raise HTTPException(429, 'Too many failed referral attempts. Try again in 24 hours.')

    # ── Look up referrer ──────────────────────────────────────────
    referrer = await db.fetchrow(
        'SELECT id, signup_ip, stripe_customer_id FROM users WHERE referral_code=$1',
        code,
    )
    if not referrer:
        # Log the failed attempt for cooldown tracking
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
            (user['id'], 'referral_failed', f'Invalid code: {code}'),
        )
        raise HTTPException(400, 'Invalid referral code')

    # ── Cannot refer yourself ─────────────────────────────────────
    if str(referrer['id']) == str(user['id']):
        raise HTTPException(400, 'You cannot refer yourself')

    # ── FIX-5a: IP subnet fraud check ─────────────────────────────
    client_ip  = get_remote_address(request)
    referrer_ip = referrer.get('signup_ip') or ''
    if referrer_ip and _same_subnet(client_ip, referrer_ip, prefix=24):
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
            (user['id'], 'referral_voided', f'IP subnet match: {client_ip} ≈ {referrer_ip}'),
        )
        raise HTTPException(400, 'Referral not eligible — accounts appear to share a network')

    # ── Link referral (reward issued on subscription, see webhook) ─
    await db.execute(
        'UPDATE users SET referred_by=$1, referral_applied_at=NOW() WHERE id=$2',
        referrer['id'], user['id'],
    )
    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        (user['id'], 'referral_applied', f'Code {code} — referrer: {referrer["id"]}'),
    )
    return {'status': 'applied', 'message': '1 month free will be applied when you subscribe'}


@router.post('/referral/webhook/subscription-created')
async def on_subscription_created(
    stripe_customer_id: str,
    db=Depends(get_db),
):
    """
    Called from the Stripe webhook handler when subscription.created fires.
    Issues rewards only after verifying card fingerprints don't match (FIX-5b).
    """
    # Find the new subscriber
    new_user = await db.fetchrow(
        'SELECT id, referred_by, stripe_customer_id FROM users WHERE stripe_customer_id=$1',
        stripe_customer_id,
    )
    if not new_user or not new_user.get('referred_by'):
        return {'status': 'no_referral'}

    referrer = await db.fetchrow(
        'SELECT id, stripe_customer_id FROM users WHERE id=$1',
        new_user['referred_by'],
    )
    if not referrer:
        return {'status': 'referrer_not_found'}

    # ── FIX-5b: Stripe card fingerprint fraud check ───────────────
    new_fp      = await _get_stripe_card_fingerprint(stripe_customer_id)
    referrer_fp = await _get_stripe_card_fingerprint(referrer['stripe_customer_id'])

    if new_fp and referrer_fp and new_fp == referrer_fp:
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
            (new_user['id'], 'referral_reward_voided',
             'Same Stripe card fingerprint — fraud detected'),
        )
        return {'status': 'voided', 'reason': 'same_payment_method'}

    # ── Issue rewards ─────────────────────────────────────────────
    # New subscriber: 1 month free via one-time coupon
    coupon = stripe.Coupon.create(percent_off=100, duration='once')
    stripe.Subscription.modify(
        await _get_active_subscription_id(stripe_customer_id),
        coupon=coupon.id,
    )

    # Referrer: $79 credit (1 month Trader) via customer balance
    stripe.Customer.create_balance_transaction(
        referrer['stripe_customer_id'],
        amount=-7900,
        currency='usd',
        description='Referral reward — 1 month free',
    )

    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        (new_user['id'], 'referral_reward_issued', 'Coupon applied to new subscriber'),
    )
    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        (referrer['id'], 'referral_reward_issued', '$79 credit applied to referrer'),
    )
    return {'status': 'rewards_issued'}


async def _get_active_subscription_id(stripe_customer_id: str) -> str:
    subs = stripe.Subscription.list(customer=stripe_customer_id, status='active')
    if subs and subs.data:
        return subs.data[0].id
    raise HTTPException(500, 'No active subscription found for this customer')
