# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

```
api/
  auth.py              — JWT auth endpoints + get_current_user dependency
  billing.py           — Stripe/Paystack subscription management + webhook handler
  middleware/
    rate_limit.py      — in-memory sliding-window rate limiter (Depends factory)
  routes/
    admin.py           — admin stats, user management, plan config, branding, backups
    admin_pairs.py     — trading pair management + per-pair backtest runner
    analytics.py       — performance analytics from materialized views
    auditlog.py        — user audit log read
    community.py       — Telegram community channel management + signal/result drops
    data_management.py — OHLC data info and upload (admin only)
    model.py           — model version registry + retrain trigger
    news.py            — economic calendar (Finnhub) with plan-gated access
    prices.py          — live price ticker (public)
    profile.py         — user profile read/update + password change
    referral.py        — referral code and reward system
    regime.py          — D1 market structure for all pairs (reads ohlc_h4)
    settings.py        — user trading/risk/notification settings
    signals.py         — trade signals list + approve/reject
    trades.py          — trade history
    trial.py           — 14-day trial activation
```

## Auth (`api/auth.py`)

### `get_current_user` dependency

Decodes the Bearer JWT and returns the raw payload. **Stateless — no DB call.** Import and use in any route that needs authentication:

```python
from api.auth import get_current_user

@router.get("/example")
async def example(user=Depends(get_current_user)):
    user["sub"]      # UUID string (user ID)
    user["email"]    # email address
    user["plan"]     # plan name: community | starter | trader | pro | elite | trial
    user["is_admin"] # bool
```

Because `get_current_user` is stateless, the `plan` and `is_admin` values in the token may be up to `JWT_EXPIRE_MINUTES` stale. For destructive admin operations use `_require_admin_live(user, db)` which does a live DB check.

### Token pair

Access token: HS256, configured TTL (default 60 min), includes `sub/email/plan/is_admin`.
Refresh token: 30-day TTL, includes a `jti` stored in `refresh_token_jti` table. Rotation is single-use — the jti is deleted atomically on exchange. Password reset revokes all refresh tokens for the user.

### Password rules

8+ characters, at least one uppercase letter, at least one digit. Enforced by Pydantic validators on `RegisterRequest` and `ResetPasswordRequest`.

### Password reset

Token stored in `password_reset_tokens`, 15-minute expiry, single-use (`used = TRUE` after redemption). Email sent via SMTP configured in `bot_config` (reads `smtp_host/port/user/password/from_email`); logs the link if SMTP is not configured. `forgot-password` always returns 200 — never reveals whether an email is registered. Rate-limited to 3/hour.

### Rate limits on auth endpoints

| Endpoint | Limit |
|---|---|
| `/auth/register` | 10 / 60 s |
| `/auth/login` | 10 / 60 s |
| `/auth/forgot-password` | 3 / 3600 s |
| `/auth/reset-password` | 5 / 3600 s |

## RLS + Auth Pattern

Every route that reads or writes user-owned rows (`trades`, `trade_signals`, `risk_state`, `feature_store`, `audit_log`) must call `set_rls_user` after acquiring `db`:

```python
from database.connection import get_db, set_rls_user

@router.get("/trades")
async def list_trades(user=Depends(get_current_user), db=Depends(get_db)):
    await set_rls_user(db, user["sub"])   # ← required before any user-owned table access
    rows = await db.fetch("SELECT * FROM trades WHERE user_id=$1", user["sub"])
```

Omitting `set_rls_user` causes RLS to return zero rows silently — not an error, just missing data.

Admin routes that query across all users (e.g. `GET /admin/stats`) do **not** call `set_rls_user` — they rely on the `trading_admin` role bypassing RLS, or query tables that don't have RLS enabled (`users`, `plan_config`, `bot_config`).

## Plan Gating

Plan access is enforced at the route layer, not at the DB layer. Each route file defines its own plan sets and guard functions:

| Guard | Scope | Plans allowed |
|---|---|---|
| `_require_paid(user)` | signals, analytics, news | starter, trader, pro, elite, trial |
| `_require_admin(user)` | admin routes, model routes | `is_admin == True` (JWT check) |
| `_require_admin_live(user, db)` | destructive admin ops | live DB re-check of `is_admin` |
| Inline plan check | approve/reject signals | trader, pro, elite |
| Inline plan check | auto-execute, copy trade | checked in settings PATCH |

`community` plan users can receive Telegram channel drops but cannot access any authenticated dashboard features.

## Billing (`api/billing.py`)

### Payment gateway

Payment config is read from `bot_config` at request time and falls back to `.env`/`config.py` for each field. This allows the admin to switch gateways and update Stripe price IDs without redeploying.

### Plan changes on existing subscriptions

When a user with an active Stripe subscription starts a checkout for a different plan, the route calls `stripe.Subscription.modify()` on the existing subscription — it does **not** create a new checkout session. Creating a new session for an existing subscriber causes double billing. New subscriptions (no existing active sub) still use `stripe.checkout.Session.create()`.

### Webhook handler (`POST /billing/webhook`)

- No auth — verified by Stripe HMAC signature (`stripe.Webhook.construct_event`)
- Idempotency: every processed event ID is recorded in `billing_events` table; duplicate deliveries are silently skipped
- Events handled: `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`
- Each plan change uses `SELECT ... FOR UPDATE` on the user row to prevent concurrent webhook races
- `subscription.deleted` → downgrades plan to `community`

### Paystack

Paystack support is present for NGN payments. Plan codes are read from `bot_config` (`paystack_plan_*`). The gateway field in `bot_config` determines which gateway the checkout session endpoint uses.

## Route Index

| Prefix | Module | Auth required | Admin only |
|---|---|---|---|
| `/auth/*` | `api/auth.py` | No (except `/refresh`) | No |
| `/billing/*` | `api/billing.py` | Yes (except `/webhook`) | No |
| `/signals` | `routes/signals.py` | Yes | No (Starter+) |
| `/trades` | `routes/trades.py` | Yes | No |
| `/analytics/*` | `routes/analytics.py` | Yes | No (Starter+) |
| `/audit/*` | `routes/auditlog.py` | Yes | No |
| `/settings` | `routes/settings.py` | Yes | No |
| `/profile` | `routes/profile.py` | Yes | No |
| `/referral/*` | `routes/referral.py` | Yes | No |
| `/regime/*` | `routes/regime.py` | Yes | No |
| `/news/*` | `routes/news.py` | Yes | No (Starter+) |
| `/prices` | `routes/prices.py` | No | No |
| `/model/*` | `routes/model.py` | Yes | Yes |
| `/trial/*` | `routes/trial.py` | Yes | No |
| `/community/*` | `routes/community.py` | Yes | Yes |
| `/admin/*` | `routes/admin.py` | Yes | Yes |
| `/admin/pairs/*` | `routes/admin_pairs.py` | Yes | Yes |
| `/admin/data/*` | `routes/data_management.py` | Yes | Yes |
| `/config/branding` | `routes/admin.py` | No | No (public) |

## Rate Limiter (`middleware/rate_limit.py`)

In-memory sliding-window keyed by client IP. State is per-process — **does not coordinate across workers**. Use as a `Depends` factory:

```python
_=Depends(rate_limit(limit=10, window=60))   # 10 requests per 60 seconds per IP
```

Currently applied only to auth endpoints. For multi-process deployments this should be replaced with a Redis-backed counter.

## Non-Negotiable Rules

- **Never create a new Stripe checkout session for a plan change on an existing active subscription.** Use `stripe.Subscription.modify()` — new sessions cause double billing.
- **Stripe webhook signature must always be verified** with `stripe.Webhook.construct_event` before processing. Never process webhook payloads without signature validation.
- **`_require_admin(user)` checks the JWT claim.** Use `_require_admin_live(user, db)` on any endpoint that performs irreversible or destructive operations — JWT-based checks allow up to one token TTL of staleness after an admin is demoted.
- **`set_rls_user` before any user-owned table access.** Routes that skip it return empty data silently with no error, which is extremely hard to debug.
- **`forgot-password` always returns 200.** Never reveal whether an email is registered — this leaks user enumeration.
- **Billing webhook events are idempotent via `billing_events`.** Never remove the idempotency check — Stripe retries failed webhooks and each retry would otherwise double-apply the plan change.
- **Payment config is read from `bot_config` at request time**, not cached at startup. Admin changes to Stripe keys or price IDs take effect immediately without restart.
