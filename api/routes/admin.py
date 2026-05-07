"""
api/routes/admin.py — Admin-only stats, user list, audit log, and plan config.
Only accessible to users with plan='elite'.
"""
import json
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from typing import Any
from database.connection import get_db
from api.auth import get_current_user

router = APIRouter(tags=["admin"])


def _require_admin(user):
    if not user.get("is_admin") and user.get("plan") != "elite":
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
    telegram_bot_token:         str  | None = None  # blank = keep existing
    telegram_signals_channel:   str  | None = None
    telegram_community_channel: str  | None = None
    telegram_admin_chat_id:     str  | None = None
    signals_drop_enabled:       bool | None = None
    results_drop_enabled:       bool | None = None
    notify_on_approve:          bool | None = None
    notify_on_reject:           bool | None = None
    bridge_alerts_enabled:      bool | None = None
    app_name:                   str  | None = None
    app_logo_url:               str  | None = None


@router.get("/admin/config")
async def get_bot_config(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    row = await db.fetchrow("SELECT * FROM bot_config WHERE id = 1")
    if not row:
        raise HTTPException(500, "Config table not initialised — restart the server")
    d = dict(row)
    d["telegram_bot_token_set"] = bool(d.get("telegram_bot_token"))
    d["telegram_bot_token"]     = _mask_token(d.get("telegram_bot_token", ""))
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

    # Only update token if a real value is sent (not the masked placeholder)
    if body.telegram_bot_token is not None and not body.telegram_bot_token.startswith(_TOKEN_MASK):
        updates.append(f"telegram_bot_token=${i}"); params.append(body.telegram_bot_token); i += 1

    scalar_fields = [
        ("telegram_signals_channel",   body.telegram_signals_channel),
        ("telegram_community_channel", body.telegram_community_channel),
        ("telegram_admin_chat_id",     body.telegram_admin_chat_id),
        ("signals_drop_enabled",       body.signals_drop_enabled),
        ("results_drop_enabled",       body.results_drop_enabled),
        ("notify_on_approve",          body.notify_on_approve),
        ("notify_on_reject",           body.notify_on_reject),
        ("bridge_alerts_enabled",      body.bridge_alerts_enabled),
        ("app_name",                   body.app_name),
        ("app_logo_url",               body.app_logo_url),
    ]
    for col, val in scalar_fields:
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
                "text":       "✅ <b>Test message</b> from Trading AI Admin Panel.\nYour bot is configured correctly.",
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
        return {"app_name": "Trading AI", "app_logo_url": ""}
    return {
        "app_name":     row["app_name"] or "Trading AI",
        "app_logo_url": row["app_logo_url"] or "",
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
    ALLOWED_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "svg"}
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
