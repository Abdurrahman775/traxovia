"""
api/routes/admin.py — Admin-only stats, user list, audit log, and plan config.
Only accessible to users with plan='elite'.
"""
import json
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Any
from database.connection import get_db
from api.auth import get_current_user

router = APIRouter(tags=["admin"])


def _require_admin(user):
    if user["plan"] not in {"elite"}:
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
            """SELECT id, email, plan, is_paper_mode, created_at, trial_expires_at
               FROM users WHERE email ILIKE $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
            f"%{search}%", limit, offset,
        )
    else:
        total = await db.fetchval("SELECT COUNT(*) FROM users")
        rows = await db.fetch(
            """SELECT id, email, plan, is_paper_mode, created_at, trial_expires_at
               FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2""",
            limit, offset,
        )
    users = [dict(r) for r in rows]
    for u in users:
        u["is_admin"] = u["plan"] == "elite"
        if u.get("created_at"):
            u["created_at"] = u["created_at"].isoformat()
        if u.get("trial_expires_at"):
            u["trial_expires_at"] = u["trial_expires_at"].isoformat()
    return {"total": total, "users": users}


@router.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    body: dict,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    updates, params, i = [], [], 1
    if "plan" in body:
        updates.append(f"plan=${i}"); params.append(body["plan"]); i += 1
    if "is_paper_mode" in body:
        updates.append(f"is_paper_mode=${i}"); params.append(bool(body["is_paper_mode"])); i += 1
    if not updates:
        return {"status": "nothing_to_update"}
    params.append(user_id)
    await db.execute(
        f"UPDATE users SET {', '.join(updates)} WHERE id=${i}", *params
    )
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
