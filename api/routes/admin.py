"""
api/routes/admin.py — Admin-only stats, user list, audit log, and plan config.
Only accessible to users with plan='elite'.
"""
import json
import sys
import shutil
import subprocess
import platform
import logging
from pathlib import Path
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)
from typing import Any
from database.connection import get_db, _get_pool
from api.auth import get_current_user

router = APIRouter(tags=["admin"])


def _require_admin(user):
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin access required")


async def _require_admin_live(user, db):
    """Live DB check — use on destructive endpoints so revoked admins can't act during token validity window."""
    _require_admin(user)
    row = await db.fetchval("SELECT is_admin FROM users WHERE id=$1::uuid", user["sub"])
    if not row:
        raise HTTPException(403, "Admin access required")


@router.get("/admin/stats")
async def admin_stats(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    total_users  = await db.fetchval("SELECT COUNT(*) FROM users")
    admin_count  = await db.fetchval("SELECT COUNT(*) FROM users WHERE plan='elite'")
    new_week     = await db.fetchval("SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '7 days'")
    new_month    = await db.fetchval("SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '30 days'")
    plans        = await db.fetch("SELECT plan, COUNT(*) AS count FROM users GROUP BY plan ORDER BY count DESC")
    total_sigs   = await db.fetchval("SELECT COUNT(*) FROM trade_signals")
    approved     = await db.fetchval("SELECT COUNT(*) FROM trade_signals WHERE status='approved'")
    rejected     = await db.fetchval("SELECT COUNT(*) FROM trade_signals WHERE status='rejected'")
    pending      = await db.fetchval("SELECT COUNT(*) FROM trade_signals WHERE status='pending'")
    total_trades = await db.fetchval("SELECT COUNT(*) FROM trades")
    open_trades  = await db.fetchval("SELECT COUNT(*) FROM trades WHERE status='open'")
    mrr          = await db.fetchval(
        "SELECT COALESCE(SUM(pc.price), 0) FROM users u "
        "JOIN plan_config pc ON u.plan = pc.plan_id WHERE pc.price > 0"
    )
    return {
        "users": {
            "total_users":    total_users,
            "admin_count":    admin_count,
            "new_this_week":  new_week,
            "new_this_month": new_month,
        },
        "plan_distribution": [{"plan": r["plan"], "count": r["count"]} for r in plans],
        "signals": {
            "total_signals": total_sigs,
            "approved":      approved,
            "rejected":      rejected,
            "pending":       pending,
        },
        "trades": {
            "total_trades": total_trades,
            "open_trades":  open_trades,
        },
        "revenue": {
            "mrr": float(mrr or 0),
        },
    }


@router.get("/admin/users")
async def admin_users(
    limit:  int = Query(25, le=500),
    offset: int = Query(0, ge=0),
    search: str = Query(None),
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    if search:
        total = await db.fetchval(
            "SELECT COUNT(*) FROM users WHERE email ILIKE $1", f"%{search}%"
        )
        rows = await db.fetch(
            """SELECT id, email, plan, is_admin, is_paper_mode, created_at, trial_expires_at
               FROM users WHERE email ILIKE $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
            f"%{search}%", limit, offset,
        )
    else:
        total = await db.fetchval("SELECT COUNT(*) FROM users")
        rows = await db.fetch(
            """SELECT id, email, plan, is_admin, is_paper_mode, created_at, trial_expires_at
               FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2""",
            limit, offset,
        )
    users = [dict(r) for r in rows]
    for u in users:
        if u.get("created_at"):
            u["created_at"] = u["created_at"].isoformat()
        if u.get("trial_expires_at"):
            u["trial_expires_at"] = u["trial_expires_at"].isoformat()
    return {"total": total, "users": users}


_VALID_PLANS = {"community", "starter", "trader", "pro", "elite", "trial"}


class UserPatch(BaseModel):
    plan:          str  | None = None
    is_paper_mode: bool | None = None
    is_admin:      bool | None = None


@router.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    body: UserPatch,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)

    if body.plan is not None and body.plan not in _VALID_PLANS:
        raise HTTPException(400, f"Invalid plan '{body.plan}'. Must be one of: {', '.join(sorted(_VALID_PLANS))}")

    # Validate user_id is a valid UUID
    import uuid as _uuid
    try:
        _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400, "Invalid user_id format")

    updates, params, i = [], [], 1
    for col, val in [
        ("plan",          body.plan),
        ("is_paper_mode", body.is_paper_mode),
        ("is_admin",      body.is_admin),
    ]:
        if val is not None:
            updates.append(f"{col}=${i}"); params.append(val); i += 1
    if not updates:
        return {"status": "nothing_to_update"}
    params.append(user_id)
    result = await db.execute(
        f"UPDATE users SET {', '.join(updates)} WHERE id=${i}", *params
    )
    if result == "UPDATE 0":
        raise HTTPException(404, "User not found")
    return {"status": "updated"}


@router.get("/admin/audit")
async def admin_audit(
    limit:  int = Query(25, le=200),
    offset: int = Query(0, ge=0),
    action: str = Query(None),
    search: str = Query(None),
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    conditions: list[str] = []
    params: list[Any] = []
    i = 1
    if action:
        conditions.append(f"al.action = ${i}"); params.append(action); i += 1
    if search:
        conditions.append(f"u.email ILIKE ${i}"); params.append(f"%{search}%"); i += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = await db.fetchval(
        f"SELECT COUNT(*) FROM audit_log al LEFT JOIN users u ON u.id = al.user_id {where}",
        *params,
    )
    rows = await db.fetch(
        f"""SELECT al.id, al.user_id, u.email, al.action, al.detail,
                  al.ip_address::text, al.created_at
           FROM audit_log al
           LEFT JOIN users u ON u.id = al.user_id
           {where}
           ORDER BY al.created_at DESC LIMIT ${i} OFFSET ${i + 1}""",
        *params, limit, offset,
    )
    entries = []
    for r in rows:
        d = dict(r)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        entries.append(d)
    return {"total": total, "entries": entries}


@router.get("/admin/audit/actions")
async def admin_audit_actions(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    rows = await db.fetch("SELECT DISTINCT action FROM audit_log ORDER BY action")
    return [r["action"] for r in rows]


# ── Plan config ────────────────────────────────────────────────────────────────

def _plan_row(r) -> dict:
    d = dict(r)
    d["price"] = float(d["price"])
    if isinstance(d.get("features"), str):
        try:
            d["features"] = json.loads(d["features"])
        except (ValueError, TypeError):
            d["features"] = {}
    return d


class PlanPatch(BaseModel):
    name:      str            | None = None
    price:     float          | None = None
    color:     str            | None = None
    popular:   bool           | None = None
    is_active: bool           | None = None
    features:  dict[str, Any] | None = None


@router.get("/admin/plans")
async def admin_get_plans(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    rows = await db.fetch(
        "SELECT plan_id, name, price, color, popular, sort_order, is_active, features "
        "FROM plan_config ORDER BY sort_order"
    )
    return [_plan_row(r) for r in rows]


@router.patch("/admin/plans/{plan_id}")
async def admin_update_plan(
    plan_id: str,
    body: PlanPatch,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    updates, params, i = [], [], 1

    scalar_fields = [
        ("name",      body.name),
        ("price",     body.price),
        ("color",     body.color),
        ("popular",   body.popular),
        ("is_active", body.is_active),
    ]
    for col, val in scalar_fields:
        if val is not None:
            updates.append(f"{col}=${i}"); params.append(val); i += 1

    if body.features is not None:
        updates.append(f"features=${i}::jsonb")
        params.append(json.dumps(body.features)); i += 1

    if not updates:
        return {"status": "nothing_to_update"}

    updates.append("updated_at=NOW()")
    params.append(plan_id)
    await db.execute(
        f"UPDATE plan_config SET {', '.join(updates)} WHERE plan_id=${i}",
        *params,
    )
    row = await db.fetchrow(
        "SELECT plan_id, name, price, color, popular, sort_order, is_active, features "
        "FROM plan_config WHERE plan_id=$1",
        plan_id,
    )
    return _plan_row(row)


class PlanCreate(BaseModel):
    plan_id:   str
    name:      str
    price:     float
    color:     str   = '#8899b4'
    popular:   bool  = False
    is_active: bool  = True
    features:  dict[str, Any] = {}


@router.post("/admin/plans")
async def admin_create_plan(
    body: PlanCreate,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    existing = await db.fetchval(
        "SELECT plan_id FROM plan_config WHERE plan_id=$1", body.plan_id
    )
    if existing:
        raise HTTPException(400, f"Plan '{body.plan_id}' already exists")

    max_order = await db.fetchval("SELECT COALESCE(MAX(sort_order), -1) FROM plan_config") or 0
    await db.execute(
        """INSERT INTO plan_config (plan_id, name, price, color, popular, is_active, sort_order, features)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)""",
        body.plan_id, body.name, body.price, body.color,
        body.popular, body.is_active, max_order + 1,
        json.dumps(body.features),
    )
    row = await db.fetchrow(
        "SELECT plan_id, name, price, color, popular, sort_order, is_active, features "
        "FROM plan_config WHERE plan_id=$1",
        body.plan_id,
    )
    return _plan_row(row)


@router.delete("/admin/plans/{plan_id}")
async def admin_delete_plan(
    plan_id: str,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    in_use = await db.fetchval(
        "SELECT COUNT(*) FROM users WHERE plan=$1", plan_id
    ) or 0
    if in_use > 0:
        raise HTTPException(
            400, f"Cannot delete: {in_use} user(s) are on this plan. Change their plan first."
        )
    deleted = await db.fetchval(
        "DELETE FROM plan_config WHERE plan_id=$1 RETURNING plan_id", plan_id
    )
    if not deleted:
        raise HTTPException(404, "Plan not found")
    return {"status": "deleted", "plan_id": plan_id}


# ── Bot / Telegram config ──────────────────────────────────────────────────────

_TOKEN_MASK = "••••••••"


def _mask_token(token: str) -> str:
    if not token:
        return ""
    return _TOKEN_MASK + token[-4:]


class BotConfigPatch(BaseModel):
    # Telegram
    telegram_bot_token:         str  | None = None
    telegram_signals_channel:   str  | None = None
    telegram_community_channel: str  | None = None
    telegram_admin_chat_id:     str  | None = None
    signals_drop_enabled:       bool | None = None
    results_drop_enabled:       bool | None = None
    notify_on_approve:          bool | None = None
    notify_on_reject:           bool | None = None
    bridge_alerts_enabled:      bool | None = None
    # Branding
    app_name:                   str  | None = None
    app_logo_url:               str  | None = None
    # Finnhub
    finnhub_api_key:            str  | None = None
    # Email / SMTP
    smtp_host:                  str  | None = None
    smtp_port:                  int  | None = None
    smtp_user:                  str  | None = None
    smtp_password:              str  | None = None
    smtp_from_email:            str  | None = None
    smtp_from_name:             str  | None = None
    smtp_enabled:               bool | None = None
    # Payment gateway
    paystack_secret_key:        str  | None = None
    paystack_public_key:        str  | None = None
    paystack_plan_starter:      str  | None = None
    paystack_plan_trader:       str  | None = None
    paystack_plan_pro:          str  | None = None
    paystack_plan_elite:        str  | None = None
    # Feature flags
    registration_enabled:       bool | None = None
    maintenance_mode:           bool | None = None
    trial_enabled:              bool | None = None
    telegram_login_enabled:     bool | None = None


# Fields that are masked with last-4 visible
_SECRET_FIELDS = {
    "telegram_bot_token", "finnhub_api_key",
    "smtp_password", "paystack_secret_key",
}


@router.get("/admin/config")
async def get_bot_config(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    row = await db.fetchrow("SELECT * FROM bot_config WHERE id = 1")
    if not row:
        raise HTTPException(500, "Config table not initialised — restart the server")
    d = dict(row)
    # Mask secrets and add _set bool flags
    for field in _SECRET_FIELDS:
        raw = d.get(field, "")
        d[f"{field}_set"] = bool(raw)
        d[field] = _mask_token(raw or "")
    if d.get("updated_at"):
        d["updated_at"] = d["updated_at"].isoformat()
    return d


@router.patch("/admin/config")
async def update_bot_config(
    body: BotConfigPatch,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    updates, params, i = [], [], 1

    # Secrets: only write if value is real (not the masked placeholder)
    for field in _SECRET_FIELDS:
        val = getattr(body, field, None)
        if val is not None and not val.startswith(_TOKEN_MASK):
            updates.append(f"{field}=${i}"); params.append(val); i += 1
            logger.info("admin: updating secret field '%s'", field)

    scalar_fields = [
        "telegram_signals_channel", "telegram_community_channel",
        "telegram_admin_chat_id", "signals_drop_enabled", "results_drop_enabled",
        "notify_on_approve", "notify_on_reject", "bridge_alerts_enabled",
        "app_name", "app_logo_url",
        "smtp_host", "smtp_port", "smtp_user", "smtp_from_email",
        "smtp_from_name", "smtp_enabled",
        "payment_gateway",
        "paystack_public_key",
        "paystack_plan_starter", "paystack_plan_trader",
        "paystack_plan_pro", "paystack_plan_elite",
        "registration_enabled", "maintenance_mode",
        "trial_enabled", "telegram_login_enabled",
    ]
    for col in scalar_fields:
        val = getattr(body, col, None)
        if val is not None:
            updates.append(f"{col}=${i}"); params.append(val); i += 1

    if not updates:
        return {"status": "nothing_to_update"}

    updates.append("updated_at=NOW()")
    await db.execute(
        f"UPDATE bot_config SET {', '.join(updates)} WHERE id=1",
        *params,
    )
    return {"status": "saved"}


@router.post("/admin/config/test-telegram")
async def test_telegram(user=Depends(get_current_user), db=Depends(get_db)):
    """Verify the bot token by calling Telegram getMe."""
    _require_admin(user)
    row = await db.fetchrow("SELECT telegram_bot_token FROM bot_config WHERE id=1")
    token = row["telegram_bot_token"] if row else ""
    if not token:
        raise HTTPException(400, "Bot token is not configured yet.")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")

    data = resp.json()
    if not data.get("ok"):
        raise HTTPException(400, data.get("description", "Invalid bot token"))

    bot = data["result"]
    # Cache username so GET /settings doesn't need a live Telegram call
    await db.execute(
        "UPDATE bot_config SET telegram_bot_username=$1 WHERE id=1",
        bot["username"],
    )
    return {
        "ok":           True,
        "username":     bot["username"],
        "display_name": bot["first_name"],
        "bot_id":       bot["id"],
    }


@router.post("/admin/config/test-finnhub")
async def test_finnhub(user=Depends(get_current_user), db=Depends(get_db)):
    """Verify the Finnhub API key by testing basic quote access."""
    _require_admin(user)
    row = await db.fetchrow("SELECT finnhub_api_key FROM bot_config WHERE id=1")
    key = row["finnhub_api_key"] if row else ""
    if not key:
        raise HTTPException(400, "Finnhub API key is not configured yet.")

    # Test with basic quote endpoint (works on free tier) and
    # economic calendar (requires paid plan) in one client session.
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": "AAPL", "token": key},
        )

        if resp.status_code == 401:
            raise HTTPException(400, "Invalid API key — check your Finnhub dashboard.")
        if resp.status_code == 403:
            raise HTTPException(400, "API key valid but Economic Calendar requires paid Finnhub plan (not free tier).")
        if resp.status_code == 429:
            raise HTTPException(400, "Rate limit hit — key is valid but throttled. Try again in a minute.")
        if resp.status_code != 200:
            raise HTTPException(400, f"Finnhub returned HTTP {resp.status_code}")

        # Test economic calendar endpoint to check plan level
        resp2 = await client.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params={"from": "2026-07-08", "to": "2026-07-08", "token": key},
        )

    if resp2.status_code == 403:
        return {
            "ok": True,
            "message": "✓ API key valid but Economic Calendar requires paid plan. News features will be limited.",
            "has_calendar": False,
        }

    if resp2.status_code == 200:
        data = resp2.json()
        events = data.get("economicCalendar", [])
        high = sum(1 for e in events if e.get("impact", "").lower() == "high")
        return {
            "ok": True,
            "events_today": len(events),
            "high_impact": high,
            "message": f"✓ Connected with full access. {len(events)} events today, {high} high-impact.",
            "has_calendar": True,
        }

    return {
        "ok": True,
        "message": "✓ API key valid for basic endpoints.",
        "has_calendar": False,
    }


@router.post("/admin/config/test-email")
async def test_email(user=Depends(get_current_user), db=Depends(get_db)):
    """Send a test email using the configured SMTP settings."""
    import smtplib, ssl
    from email.mime.text import MIMEText
    _require_admin(user)
    row = await db.fetchrow(
        "SELECT smtp_host, smtp_port, smtp_user, smtp_password, smtp_from_email, smtp_from_name FROM bot_config WHERE id=1"
    )
    if not row or not row["smtp_host"]:
        raise HTTPException(400, "SMTP is not configured yet.")

    host       = row["smtp_host"].strip()
    port       = row["smtp_port"] or 587
    username   = row["smtp_user"].strip()
    password   = row["smtp_password"]
    from_email = row["smtp_from_email"].strip() or username
    from_name  = row["smtp_from_name"].strip() or "Trading Bot"
    to_email   = (await db.fetchval("SELECT email FROM users WHERE is_admin=true LIMIT 1")) or from_email

    msg = MIMEText("<h2>✅ SMTP Test Successful</h2><p>Your email configuration is working correctly.</p>", "html")
    msg["Subject"] = "Test Email — Trading Bot"
    msg["From"]    = f"{from_name} <{from_email}>"
    msg["To"]      = to_email

    try:
        if port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=10) as s:
                if username and password:
                    s.login(username, password)
                s.sendmail(from_email, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=10) as s:
                s.ehlo()
                s.starttls(context=ssl.create_default_context())
                if username and password:
                    s.login(username, password)
                s.sendmail(from_email, [to_email], msg.as_string())
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(400, "SMTP authentication failed — check username and password.")
    except smtplib.SMTPConnectError:
        raise HTTPException(400, f"Could not connect to {host}:{port} — check host and port.")
    except Exception as e:
        raise HTTPException(400, f"SMTP error: {e}")

    return {"ok": True, "message": f"Test email sent to {to_email}"}


@router.post("/admin/config/test-payment")
async def test_payment(user=Depends(get_current_user), db=Depends(get_db)):
    """Verify the configured payment gateway credentials."""
    _require_admin(user)
    row = await db.fetchrow(
        "SELECT payment_gateway, stripe_secret_key, paystack_secret_key FROM bot_config WHERE id=1"
    )
    if not row:
        raise HTTPException(400, "Config not initialised.")

    gateway = (row["payment_gateway"] or "stripe").lower()

    if gateway == "stripe":
        key = row["stripe_secret_key"] or ""
        if not key:
            raise HTTPException(400, "Stripe secret key is not configured.")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.stripe.com/v1/account",
                headers={"Authorization": f"Bearer {key}"},
            )
        if resp.status_code == 401:
            raise HTTPException(400, "Invalid Stripe secret key.")
        if resp.status_code != 200:
            raise HTTPException(400, f"Stripe returned HTTP {resp.status_code}")
        data = resp.json()
        return {
            "ok": True,
            "gateway": "stripe",
            "message": f"Connected. Account: {data.get('email') or data.get('id')}",
        }

    elif gateway == "paystack":
        key = row["paystack_secret_key"] or ""
        if not key:
            raise HTTPException(400, "Paystack secret key is not configured.")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.paystack.co/bank",
                headers={"Authorization": f"Bearer {key}"},
            )
        if resp.status_code == 401:
            raise HTTPException(400, "Invalid Paystack secret key.")
        if resp.status_code != 200:
            raise HTTPException(400, f"Paystack returned HTTP {resp.status_code}")
        data = resp.json()
        return {
            "ok": True,
            "gateway": "paystack",
            "message": f"Connected. {data.get('message', 'Paystack key is valid.')}",
        }

    raise HTTPException(400, f"Unknown gateway: {gateway}")


class TestMessageRequest(BaseModel):
    channel: str  # "signals" | "community" | "admin" | or a raw chat_id


@router.post("/admin/config/test-message")
async def test_message(
    body: TestMessageRequest,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Send a test message to one of the configured channels."""
    _require_admin(user)
    row = await db.fetchrow("SELECT * FROM bot_config WHERE id=1")
    if not row:
        raise HTTPException(500, "Config not found")

    token = row["telegram_bot_token"]
    if not token:
        raise HTTPException(400, "Bot token is not configured.")

    channel_map = {
        "signals":   row["telegram_signals_channel"],
        "community": row["telegram_community_channel"],
        "admin":     row["telegram_admin_chat_id"],
    }
    chat_id = channel_map.get(body.channel, body.channel)
    if not chat_id:
        raise HTTPException(400, f"Channel '{body.channel}' is not configured.")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id":    chat_id,
                "text":       "✅ <b>Test message</b> from Traxovia AI Admin Panel.\nYour bot is configured correctly.",
                "parse_mode": "HTML",
            },
        )

    data = resp.json()
    if not data.get("ok"):
        raise HTTPException(400, data.get("description", "Failed to send message. Check the channel ID and make sure the bot is an admin of the channel."))

    return {"ok": True, "chat_id": chat_id}


# ── Branding ───────────────────────────────────────────────────────────────────

@router.get("/config/branding")
async def get_branding(db=Depends(get_db)):
    """Public — no auth required. Returns app name and logo for the UI."""
    row = await db.fetchrow(
        "SELECT app_name, app_logo_url FROM bot_config WHERE id=1"
    )
    if not row:
        return {"app_name": "Traxovia AI", "app_logo_url": ""}
    return {
        "app_name":     row["app_name"] or "Traxovia AI",
        "app_logo_url": row["app_logo_url"] or "",
    }


@router.get("/config/flags")
async def get_flags(db=Depends(get_db)):
    """Public — returns site feature flags for the frontend."""
    row = await db.fetchrow(
        "SELECT registration_enabled, maintenance_mode, trial_enabled, "
        "telegram_login_enabled FROM bot_config WHERE id=1"
    )
    if not row:
        return {"registration_enabled": True, "maintenance_mode": False,
                "trial_enabled": True, "telegram_login_enabled": True}
    return {
        "registration_enabled":   row["registration_enabled"],
        "maintenance_mode":       row["maintenance_mode"],
        "trial_enabled":          row["trial_enabled"],
        "telegram_login_enabled": row["telegram_login_enabled"],
    }


@router.post("/admin/config/logo")
async def upload_logo(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Upload a logo image — saved to disk, URL stored in the DB."""
    _require_admin(user)
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image (PNG, JPG, SVG, etc.)")

    data = await file.read()
    if len(data) > 2 * 1024 * 1024:  # 2 MB limit
        raise HTTPException(400, "Image must be under 2 MB")

    import uuid, pathlib
    ALLOWED_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
    ext = (file.filename or "logo").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"Invalid file type '.{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTS))}")
    static_dir = pathlib.Path("static/logos")
    static_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    (static_dir / filename).write_bytes(data)

    logo_url = f"/static/logos/{filename}"
    await db.execute(
        "UPDATE bot_config SET app_logo_url=$1, updated_at=NOW() WHERE id=1",
        logo_url,
    )
    return {"app_logo_url": logo_url}


# ── Backup ─────────────────────────────────────────────────────────────────────

def _pg_url() -> str:
    """Return a libpq-compatible connection string from settings DATABASE_URL."""
    from config import settings
    url = settings.database_url or ""
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("asyncpg://", "postgresql://")


@router.post("/admin/backup/create")
async def backup_create(user=Depends(get_current_user), db=Depends(get_db)):
    await _require_admin_live(user, db)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename  = f"backup_{timestamp}.sql"
    filepath  = BACKUP_DIR / filename
    try:
        result = subprocess.run(
            ["pg_dump", "--no-password", "--clean", "--if-exists",
             "-f", str(filepath), _pg_url()],
            capture_output=True, text=True, timeout=180,
        )
    except FileNotFoundError:
        raise HTTPException(500, "pg_dump not found — install postgresql-client inside the container.")
    if result.returncode != 0:
        filepath.unlink(missing_ok=True)
        raise HTTPException(500, f"pg_dump failed: {result.stderr[:400]}")
    size = filepath.stat().st_size
    return {"filename": filename, "size": size, "created_at": datetime.now(timezone.utc).isoformat()}


@router.get("/admin/backup/list")
async def backup_list(user=Depends(get_current_user), db=Depends(get_db)):
    await _require_admin_live(user, db)
    files = sorted(BACKUP_DIR.glob("*.sql"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [
        {
            "filename": f.name,
            "size":     f.stat().st_size,
            "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
        }
        for f in files
    ]


@router.get("/admin/backup/download/{filename}")
async def backup_download(filename: str, user=Depends(get_current_user), db=Depends(get_db)):
    await _require_admin_live(user, db)
    if "/" in filename or ".." in filename or not filename.endswith(".sql"):
        raise HTTPException(400, "Invalid filename")
    filepath = BACKUP_DIR / filename
    if not filepath.exists():
        raise HTTPException(404, "Backup not found")
    return FileResponse(str(filepath), filename=filename, media_type="application/octet-stream")


@router.delete("/admin/backup/{filename}")
async def backup_delete(filename: str, user=Depends(get_current_user), db=Depends(get_db)):
    await _require_admin_live(user, db)
    if "/" in filename or ".." in filename or not filename.endswith(".sql"):
        raise HTTPException(400, "Invalid filename")
    filepath = BACKUP_DIR / filename
    if not filepath.exists():
        raise HTTPException(404, "Backup not found")
    filepath.unlink()
    return {"status": "deleted"}


@router.post("/admin/backup/restore")
async def backup_restore(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    await _require_admin_live(user, db)
    if not (file.filename or "").endswith(".sql"):
        raise HTTPException(400, "Only .sql files are accepted")
    data = await file.read()
    if len(data) > 200 * 1024 * 1024:
        raise HTTPException(400, "File exceeds 200 MB limit")
    tmp = BACKUP_DIR / f"restore_tmp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.sql"
    tmp.write_bytes(data)
    try:
        result = subprocess.run(
            ["psql", "--no-password", "-f", str(tmp), _pg_url()],
            capture_output=True, text=True, timeout=300,
        )
    except FileNotFoundError:
        raise HTTPException(500, "psql not found — install postgresql-client inside the container.")
    finally:
        tmp.unlink(missing_ok=True)
    if result.returncode != 0:
        raise HTTPException(500, f"Restore failed: {result.stderr[:500]}")
    return {"status": "restored", "filename": file.filename}


class ClearRequest(BaseModel):
    scope:   str  # trading_data | audit_log | all_data
    confirm: str  # must be "CONFIRM"


_CLEAR_SCOPES: dict[str, list[str]] = {
    "trading_data": ["trades", "trade_signals"],
    "audit_log":    ["audit_log"],
    "all_data":     ["trades", "trade_signals", "audit_log"],
}


@router.post("/admin/backup/clear")
async def backup_clear(body: ClearRequest, user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    if body.confirm != "CONFIRM":
        raise HTTPException(400, "confirmation must be the string CONFIRM")
    tables = _CLEAR_SCOPES.get(body.scope)
    if not tables:
        raise HTTPException(400, f"Invalid scope. Choose: {', '.join(_CLEAR_SCOPES)}")
    cleared: list[str] = []
    for table in tables:
        try:
            await db.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
            cleared.append(table)
        except Exception as exc:
            logger.warning("TRUNCATE %s failed: %s", table, exc)
    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        user["sub"], "db_clear", f"scope={body.scope} tables={cleared}",
    )
    return {"status": "cleared", "tables": cleared}


# ── System info & maintenance ──────────────────────────────────────────────────

@router.get("/admin/system/info")
async def system_info(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)

    pg_version = await db.fetchval("SELECT version()")
    db_name    = await db.fetchval("SELECT current_database()")
    db_size    = await db.fetchval("SELECT pg_size_pretty(pg_database_size(current_database()))")
    db_size_b  = await db.fetchval("SELECT pg_database_size(current_database())")

    table_rows = await db.fetch("""
        SELECT tablename AS name,
               pg_size_pretty(pg_total_relation_size(quote_ident(tablename))) AS pretty_size,
               pg_total_relation_size(quote_ident(tablename)) AS size_bytes
        FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY size_bytes DESC
        LIMIT 20
    """)

    row_counts: dict[str, int] = {}
    for tbl in ["users", "trades", "trade_signals", "audit_log"]:
        try:
            row_counts[tbl] = await db.fetchval(f"SELECT COUNT(*) FROM {tbl}")
        except Exception:
            row_counts[tbl] = -1

    disk     = shutil.disk_usage("/")
    bk_files = list(BACKUP_DIR.glob("*.sql"))
    bk_size  = sum(f.stat().st_size for f in bk_files)

    return {
        "python":   sys.version.split()[0],
        "platform": platform.system() + " " + platform.release(),
        "postgres": (pg_version or "").split(",")[0],
        "db_name":  db_name,
        "db_size":  db_size,
        "db_size_bytes": db_size_b,
        "tables":   [dict(r) for r in table_rows],
        "row_counts": row_counts,
        "disk": {
            "total_gb": round(disk.total / 1e9, 1),
            "used_gb":  round(disk.used  / 1e9, 1),
            "free_gb":  round(disk.free  / 1e9, 1),
            "used_pct": round(disk.used  / disk.total * 100, 1),
        },
        "backups": {
            "count":    len(bk_files),
            "size_mb":  round(bk_size / 1e6, 2),
        },
    }


@router.post("/admin/system/vacuum")
async def system_vacuum(user=Depends(get_current_user)):
    _require_admin(user)
    # VACUUM cannot run inside a transaction block — acquire a raw pool connection
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("VACUUM ANALYZE")
    return {"status": "ok", "message": "VACUUM ANALYZE completed successfully"}


@router.post("/admin/system/reindex")
async def system_reindex(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    tables = await db.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    done: list[str] = []
    for row in tables:
        try:
            await db.execute(f"REINDEX TABLE {row['tablename']}")
            done.append(row["tablename"])
        except Exception as exc:
            logger.warning("REINDEX %s: %s", row["tablename"], exc)
    return {"status": "ok", "reindexed": done}
