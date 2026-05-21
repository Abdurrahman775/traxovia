"""
tg_bot/handlers/trade_handlers.py — Trader+ trade action commands.

Commands:
  /approve_<id>  — approve a pending signal (first 8 chars of UUID)
  /reject_<id>   — reject a pending signal
  /pause         — pause automated trading
  /resume        — resume automated trading
"""
from __future__ import annotations

from tg_bot.handlers import _TRADER_PLANS, _bot_db, _upgrade_text


async def cmd_approve(update, context) -> None:
    """Handle /approve_<signal_prefix>"""
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _TRADER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/approve", "trader"), parse_mode="HTML"
            )
            return

        text   = update.message.text or ""
        parts  = text.split("_", 1)
        prefix = parts[1].strip() if len(parts) > 1 else ""

        if len(prefix) < 4:
            await update.message.reply_text(
                "Usage: /approve_&lt;signal-id&gt;  (use first 8 chars from /signals)",
                parse_mode="HTML",
            )
            return

        row = await db.fetchrow(
            "SELECT id, status FROM trade_signals "
            "WHERE user_id=$1::uuid AND id::text LIKE $2 AND status='pending' "
            "LIMIT 1",
            user["id"], f"{prefix}%",
        )
        if not row:
            await update.message.reply_text("Signal not found or already actioned.")
            return

        await db.execute(
            "UPDATE trade_signals SET status='approved', updated_at=NOW() WHERE id=$1",
            row["id"],
        )
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
            user["id"], "signal_action", f"approved signal {row['id']} via telegram",
        )

    await update.message.reply_text(f"✅ Signal <code>{prefix}</code> approved.", parse_mode="HTML")


async def cmd_reject(update, context) -> None:
    """Handle /reject_<signal_prefix>"""
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _TRADER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/reject", "trader"), parse_mode="HTML"
            )
            return

        text   = update.message.text or ""
        parts  = text.split("_", 1)
        prefix = parts[1].strip() if len(parts) > 1 else ""

        if len(prefix) < 4:
            await update.message.reply_text(
                "Usage: /reject_&lt;signal-id&gt;  (use first 8 chars from /signals)",
                parse_mode="HTML",
            )
            return

        row = await db.fetchrow(
            "SELECT id, status FROM trade_signals "
            "WHERE user_id=$1::uuid AND id::text LIKE $2 AND status='pending' "
            "LIMIT 1",
            user["id"], f"{prefix}%",
        )
        if not row:
            await update.message.reply_text("Signal not found or already actioned.")
            return

        await db.execute(
            "UPDATE trade_signals SET status='rejected', updated_at=NOW() WHERE id=$1",
            row["id"],
        )
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
            user["id"], "signal_action", f"rejected signal {row['id']} via telegram",
        )

    await update.message.reply_text(f"❌ Signal <code>{prefix}</code> rejected.", parse_mode="HTML")


async def cmd_pause(update, context) -> None:
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _TRADER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/pause", "trader"), parse_mode="HTML"
            )
            return

        await db.execute(
            "UPDATE risk_state SET trading_allowed=FALSE, updated_at=NOW() "
            "WHERE user_id=$1::uuid",
            user["id"],
        )
        await db.execute(
            "INSERT INTO bridge_state (active_url, primary_url, standby_url, trading_paused)"
            " SELECT '','','',TRUE FROM (SELECT 1) t WHERE NOT EXISTS (SELECT 1 FROM bridge_state)"
        )
        await db.execute(
            "UPDATE bridge_state SET trading_paused=TRUE, updated_at=NOW()"
        )
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
            user["id"], "risk_change", "trading paused via telegram",
        )

    await update.message.reply_text("⏸ Automated trading paused.")


async def cmd_resume(update, context) -> None:
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _TRADER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/resume", "trader"), parse_mode="HTML"
            )
            return

        await db.execute(
            "UPDATE risk_state SET trading_allowed=TRUE, updated_at=NOW() "
            "WHERE user_id=$1::uuid",
            user["id"],
        )
        await db.execute(
            "INSERT INTO bridge_state (active_url, primary_url, standby_url, trading_paused)"
            " SELECT '','','',FALSE FROM (SELECT 1) t WHERE NOT EXISTS (SELECT 1 FROM bridge_state)"
        )
        await db.execute(
            "UPDATE bridge_state SET trading_paused=FALSE, updated_at=NOW()"
        )
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
            user["id"], "risk_change", "trading resumed via telegram",
        )

    await update.message.reply_text("▶️ Automated trading resumed.")
