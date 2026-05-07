"""
api/routes/community.py — Community channel management, manual drops, and invite links.
Admin-only (elite plan) except invite-link generation which is admin-initiated for members.
"""
from __future__ import annotations
import logging
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from typing import Any
from database.connection import get_db
from api.auth import get_current_user

router = APIRouter(prefix="/community", tags=["community"])
logger = logging.getLogger(__name__)


def _require_admin(user):
    if not user.get("is_admin") and user.get("plan") != "elite":
        raise HTTPException(403, "Admin access required")


async def _get_bot_token(db) -> str:
    row = await db.fetchrow("SELECT telegram_bot_token FROM bot_config WHERE id=1")
    token = row["telegram_bot_token"] if row else ""
    if not token:
        raise HTTPException(400, "Telegram bot token is not configured. Set it in Admin → Config.")
    return token


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def community_stats(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    members = await db.fetchval("SELECT COUNT(*) FROM users WHERE plan='community'") or 0
    signal_drops = await db.fetchval(
        "SELECT COUNT(*) FROM audit_log WHERE action='community_signal_drop'"
    ) or 0
    result_drops = await db.fetchval(
        "SELECT COUNT(*) FROM audit_log WHERE action='community_result_drop'"
    ) or 0
    converted = await db.fetchval(
        "SELECT COUNT(*) FROM users WHERE plan != 'community' AND referred_by IS NOT NULL"
    ) or 0
    conversion_rate = round((converted / members * 100), 1) if members > 0 else 0.0
    channels = await db.fetchval("SELECT COUNT(*) FROM community_channels WHERE is_active=TRUE") or 0
    return {
        "members": members,
        "signal_drops": signal_drops,
        "result_drops": result_drops,
        "conversion_rate": conversion_rate,
        "active_channels": channels,
    }


# ── Recent drops ──────────────────────────────────────────────────────────────

@router.get("/drops")
async def list_drops(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    rows = await db.fetch(
        """SELECT t.id, t.pair, t.direction, t.pnl_r, t.exit_time AS created_at
           FROM trades t
           WHERE t.status = 'closed' AND t.pnl_r IS NOT NULL
           ORDER BY t.exit_time DESC LIMIT 20"""
    )
    return [
        {
            "id": str(r["id"]),
            "pair": r["pair"],
            "direction": (r["direction"] or "").upper(),
            "pnl_r": float(r["pnl_r"]),
            "created_at": r["created_at"].strftime("%b %d") if r["created_at"] else "—",
        }
        for r in rows
    ]


# ── Manual drops ──────────────────────────────────────────────────────────────

@router.post("/drop-signal")
async def drop_signal(background_tasks: BackgroundTasks, user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    signal = await db.fetchrow(
        """SELECT id, pair, direction, entry_price, stop_loss, take_profit,
                  ai_probability, regime
           FROM trade_signals WHERE status='pending'
           ORDER BY created_at DESC LIMIT 1"""
    )
    if not signal:
        raise HTTPException(404, "No pending signal to drop")

    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        user["sub"], "community_signal_drop",
        f"Signal dropped: {signal['pair']} {signal['direction']}",
    )

    try:
        from telegram.community_drops import post_signal_drop
        background_tasks.add_task(post_signal_drop, dict(signal))
    except Exception as e:
        logger.warning("community signal drop failed: %s", e)

    return {"status": "dropped", "pair": signal["pair"], "direction": signal["direction"]}


@router.post("/drop-result")
async def drop_result(background_tasks: BackgroundTasks, user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    trade = await db.fetchrow(
        """SELECT t.id, t.pair, t.direction, t.pnl_r AS result_r, t.exit_time,
                  ts.regime, ts.ai_probability, ts.entry_price
           FROM trades t
           LEFT JOIN trade_signals ts ON ts.id = t.signal_id
           WHERE t.status='closed' AND t.pnl_r IS NOT NULL
           ORDER BY t.exit_time DESC LIMIT 1"""
    )
    if not trade:
        raise HTTPException(404, "No closed trade to drop")

    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        user["sub"], "community_result_drop",
        f"Result dropped: {trade['pair']} {float(trade['result_r']):+.2f}R",
    )

    try:
        from telegram.community_drops import post_result_drop
        trade_d = dict(trade)
        background_tasks.add_task(post_result_drop, trade_d, trade_d)
    except Exception as e:
        logger.warning("community result drop failed: %s", e)

    return {
        "status": "dropped",
        "pair": trade["pair"],
        "pnl_r": float(trade["result_r"]),
    }


# ── Channel management ────────────────────────────────────────────────────────

@router.get("/channels")
async def list_channels(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    rows = await db.fetch(
        "SELECT id, name, chat_id, channel_type, description, is_active, member_count, created_at "
        "FROM community_channels ORDER BY created_at DESC"
    )
    return [
        {
            **dict(r),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


class ChannelCreate(BaseModel):
    name: str
    chat_id: str
    channel_type: str = "community"  # signals | community | admin | general
    description: str = ""


@router.post("/channels")
async def create_channel(
    body: ChannelCreate,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    if not body.name.strip() or not body.chat_id.strip():
        raise HTTPException(400, "name and chat_id are required")
    existing = await db.fetchval(
        "SELECT id FROM community_channels WHERE chat_id=$1", body.chat_id
    )
    if existing:
        raise HTTPException(400, f"Channel with chat_id '{body.chat_id}' already exists")

    # Verify the channel is reachable via the bot
    token = await _get_bot_token(db)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": body.chat_id},
        )
    data = resp.json()
    if not data.get("ok"):
        raise HTTPException(400, f"Telegram error: {data.get('description', 'Could not reach that chat ID. Make sure the bot is a member.')}")

    tg_chat = data["result"]
    member_count = 0
    async with httpx.AsyncClient(timeout=10) as client:
        mc_resp = await client.get(
            f"https://api.telegram.org/bot{token}/getChatMemberCount",
            params={"chat_id": body.chat_id},
        )
        if mc_resp.json().get("ok"):
            member_count = mc_resp.json()["result"]

    row = await db.fetchrow(
        """INSERT INTO community_channels (name, chat_id, channel_type, description, member_count)
           VALUES ($1, $2, $3, $4, $5)
           RETURNING id, name, chat_id, channel_type, description, is_active, member_count, created_at""",
        body.name or tg_chat.get("title", body.chat_id),
        body.chat_id, body.channel_type, body.description, member_count,
    )
    return {**dict(row), "created_at": row["created_at"].isoformat() if row["created_at"] else None}


@router.delete("/channels/{channel_id}")
async def delete_channel(
    channel_id: int,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    deleted = await db.fetchval(
        "DELETE FROM community_channels WHERE id=$1 RETURNING id", channel_id
    )
    if not deleted:
        raise HTTPException(404, "Channel not found")
    return {"status": "deleted"}


class ChannelPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    channel_type: str | None = None
    is_active: bool | None = None


@router.patch("/channels/{channel_id}")
async def update_channel(
    channel_id: int,
    body: ChannelPatch,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    updates, params, i = [], [], 1
    for col, val in [("name", body.name), ("description", body.description),
                     ("channel_type", body.channel_type), ("is_active", body.is_active)]:
        if val is not None:
            updates.append(f"{col}=${i}"); params.append(val); i += 1
    if not updates:
        return {"status": "nothing_to_update"}
    params.append(channel_id)
    await db.execute(
        f"UPDATE community_channels SET {', '.join(updates)} WHERE id=${i}", *params
    )
    return {"status": "updated"}


# ── Invite link generation ────────────────────────────────────────────────────

@router.post("/channels/{channel_id}/invite-link")
async def create_invite_link(
    channel_id: int,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    row = await db.fetchrow(
        "SELECT chat_id, name FROM community_channels WHERE id=$1", channel_id
    )
    if not row:
        raise HTTPException(404, "Channel not found")

    token = await _get_bot_token(db)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{token}/createChatInviteLink",
            json={
                "chat_id": row["chat_id"],
                "name": f"Invite from Trading AI",
                "creates_join_request": False,
            },
        )
    data = resp.json()
    if not data.get("ok"):
        raise HTTPException(400, data.get("description", "Failed to create invite link. Bot must be admin of the channel."))

    return {
        "invite_link": data["result"]["invite_link"],
        "channel_name": row["name"],
    }


@router.post("/channels/{channel_id}/refresh-count")
async def refresh_member_count(
    channel_id: int,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    row = await db.fetchrow(
        "SELECT chat_id FROM community_channels WHERE id=$1", channel_id
    )
    if not row:
        raise HTTPException(404, "Channel not found")

    token = await _get_bot_token(db)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"https://api.telegram.org/bot{token}/getChatMemberCount",
            params={"chat_id": row["chat_id"]},
        )
    data = resp.json()
    if not data.get("ok"):
        raise HTTPException(400, data.get("description", "Could not fetch member count"))

    count = data["result"]
    await db.execute(
        "UPDATE community_channels SET member_count=$1 WHERE id=$2", count, channel_id
    )
    return {"member_count": count}
