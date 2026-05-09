"""
telegram/handlers/account_handlers.py — Account linking and identity commands.

Commands:
  /start            — welcome message, instructions for new users
  /help             — full command list by tier
  /link <TOKEN>     — link this Telegram account to a Traxovia AI account
  /unlink           — remove Telegram link from account
  /me               — show linked account info and plan
"""
from __future__ import annotations
from datetime import datetime, timezone

from tg_bot.handlers import _bot_db, PLAN_LABELS, TIER_COMMANDS


# ── /start ─────────────────────────────────────────────────────────────────────

async def cmd_start(update, context) -> None:
    tg_id = update.effective_user.id

    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT email, plan, telegram_username FROM users WHERE telegram_chat_id=$1",
            tg_id,
        )

    if user:
        plan_label = PLAN_LABELS.get(user["plan"], user["plan"])
        text = (
            f"👋 Welcome back, <b>{user['email']}</b>!\n\n"
            f"Plan: <b>{plan_label}</b>\n\n"
            f"Type /help to see your available commands."
        )
    else:
        text = (
            "👋 Welcome to <b>Traxovia AI</b>!\n\n"
            "This bot gives you real-time control over your trading account "
            "directly from Telegram.\n\n"
            "<b>To get started:</b>\n"
            "1. Log in to your Traxovia AI dashboard\n"
            "2. Go to <b>Settings → Telegram</b>\n"
            "3. Click <b>Generate Link Token</b>\n"
            "4. Send <code>/link YOUR_TOKEN</code> here\n\n"
            "Available commands scale with your plan tier. "
            "Type /help to see the full list."
        )

    await update.message.reply_text(text, parse_mode="HTML")


# ── /help ──────────────────────────────────────────────────────────────────────

async def cmd_help(update, context) -> None:
    await update.message.reply_text(TIER_COMMANDS, parse_mode="HTML")


# ── /link ──────────────────────────────────────────────────────────────────────

async def cmd_link(update, context) -> None:
    """
    /link <TOKEN>
    Validates the token generated in the dashboard Settings page and saves
    the Telegram chat_id to the user's account.
    """
    tg_id       = update.effective_user.id
    tg_username = update.effective_user.username or ""

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: <code>/link YOUR_TOKEN</code>\n\n"
            "Get your token from <b>Settings → Telegram</b> in the dashboard.",
            parse_mode="HTML",
        )
        return

    token = args[0].strip().upper()

    async with _bot_db() as db:
        # Check if this Telegram ID is already linked to an account
        existing = await db.fetchrow(
            "SELECT email, plan FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if existing:
            plan_label = PLAN_LABELS.get(existing["plan"], existing["plan"])
            await update.message.reply_text(
                f"✅ Already linked to <b>{existing['email']}</b> ({plan_label}).\n"
                f"Use /unlink first to switch accounts.",
                parse_mode="HTML",
            )
            return

        # Look up the token
        row = await db.fetchrow(
            """SELECT id, email, plan, telegram_link_expires_at
               FROM users
               WHERE telegram_link_token = $1""",
            token,
        )

        if not row:
            await update.message.reply_text(
                "❌ <b>Invalid token.</b>\n\n"
                "Make sure you copied it correctly from the dashboard.\n"
                "Tokens are case-insensitive. Generate a new one if needed.",
                parse_mode="HTML",
            )
            return

        # Check expiry
        expires_at = row["telegram_link_expires_at"]
        now        = datetime.now(timezone.utc)
        if expires_at is None or now > expires_at.replace(tzinfo=timezone.utc):
            await update.message.reply_text(
                "⏰ <b>Token expired.</b>\n\n"
                "Tokens are valid for 15 minutes. "
                "Go to <b>Settings → Telegram</b> and generate a new one.",
                parse_mode="HTML",
            )
            return

        # Link the account — save chat_id, clear token
        await db.execute(
            """UPDATE users
               SET telegram_chat_id        = $1,
                   telegram_username       = $2,
                   telegram_link_token     = NULL,
                   telegram_link_expires_at = NULL,
                   updated_at              = NOW()
               WHERE id = $3""",
            tg_id,
            tg_username,
            row["id"],
        )

        # Audit log
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail, ip_address) "
            "VALUES($1, $2, $3, NULL)",
            row["id"],
            "mt5_binding",
            f"Telegram account @{tg_username or tg_id} linked via /link command",
        )

    plan       = row["plan"]
    plan_label = PLAN_LABELS.get(plan, plan)

    # Tier-specific welcome message
    if plan == "community":
        extras = (
            "You'll receive community signal drops in the channel.\n"
            "Upgrade to Starter or above to use bot commands."
        )
    elif plan in ("starter", "trial"):
        extras = "You can now use /status, /pnl, /trades, /signals, and /regime."
    elif plan == "trader":
        extras = "You can approve/reject signals with /approve and /reject."
    else:
        extras = "Full command access enabled including /risk, /mode, and /weekly."

    await update.message.reply_text(
        f"✅ <b>Account linked successfully!</b>\n\n"
        f"Email: <code>{row['email']}</code>\n"
        f"Plan:  <b>{plan_label}</b>\n\n"
        f"{extras}\n\n"
        f"Type /help for a full command list.",
        parse_mode="HTML",
    )


# ── /unlink ────────────────────────────────────────────────────────────────────

async def cmd_unlink(update, context) -> None:
    tg_id = update.effective_user.id

    async with _bot_db() as db:
        row = await db.fetchrow(
            "SELECT id, email FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not row:
            await update.message.reply_text(
                "No account is linked to this Telegram. Use /link to connect."
            )
            return

        await db.execute(
            "UPDATE users SET telegram_chat_id=NULL, telegram_username=NULL, "
            "updated_at=NOW() WHERE id=$1",
            row["id"],
        )
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail, ip_address) "
            "VALUES($1, $2, $3, NULL)",
            row["id"],
            "mt5_binding",
            "Telegram account unlinked via /unlink command",
        )

    await update.message.reply_text(
        f"🔓 Telegram unlinked from <b>{row['email']}</b>.\n"
        f"Use /link to reconnect at any time.",
        parse_mode="HTML",
    )


# ── /me ────────────────────────────────────────────────────────────────────────

async def cmd_me(update, context) -> None:
    tg_id = update.effective_user.id

    async with _bot_db() as db:
        row = await db.fetchrow(
            """SELECT email, plan, is_paper_mode, created_at,
                      trial_expires_at, telegram_username
               FROM users WHERE telegram_chat_id=$1""",
            tg_id,
        )

    if not row:
        await update.message.reply_text(
            "No account linked. Use /link to connect your Traxovia AI account."
        )
        return

    plan_label = PLAN_LABELS.get(row["plan"], row["plan"])
    mode       = "📄 Paper" if row["is_paper_mode"] else "💰 Live"
    trial_line = ""
    if row["trial_expires_at"]:
        exp = row["trial_expires_at"].strftime("%Y-%m-%d")
        trial_line = f"\nTrial expires: <code>{exp}</code>"

    await update.message.reply_text(
        f"<b>Your Account</b>\n\n"
        f"Email:   <code>{row['email']}</code>\n"
        f"Plan:    <b>{plan_label}</b>\n"
        f"Mode:    {mode}{trial_line}\n"
        f"Joined:  {row['created_at'].strftime('%Y-%m-%d')}\n\n"
        f"Type /help to see available commands.",
        parse_mode="HTML",
    )
