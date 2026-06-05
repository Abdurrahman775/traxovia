"""
tg_bot/bot.py — Traxovia AI Telegram bot entry point.

Run:
    python -m tg_bot.bot          (from project root, with venv active)

Environment variables required:
    TELEGRAM_BOT_TOKEN   — token from BotFather
    DATABASE_URL         — asyncpg connection string

Command tiers:
    All users    : /start /help /link /unlink /me
    Starter+     : /status /pnl /trades /signals /risk_state /regime /accounts
    Trader+      : /approve /reject /pause /resume /bridge_status
    Pro+         : /risk /mode /weekly /dd_override /pairs /setsl
    Elite        : /api_key
"""
from __future__ import annotations
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand

load_dotenv(Path(__file__).parent.parent / ".env")
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from tg_bot.handlers.account_handlers import (
    cmd_start, cmd_help, cmd_link, cmd_unlink, cmd_me,
)
from tg_bot.handlers.status_handlers import (
    cmd_status, cmd_pnl, cmd_trades, cmd_signals,
    cmd_risk_state, cmd_regime, cmd_accounts,
)
from tg_bot.handlers.trade_handlers import (
    cmd_approve, cmd_reject, cmd_pause, cmd_resume,
)
from tg_bot.handlers.pro_handlers import (
    cmd_risk, cmd_mode, cmd_weekly, cmd_dd_override,
    cmd_bridge_status, cmd_pairs, cmd_setsl, cmd_api_key,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _get_token() -> str:
    """Read bot token: DB bot_config first, fall back to .env."""
    try:
        import psycopg2
        host     = os.getenv("DB_HOST", "localhost")
        port     = os.getenv("DB_PORT", "5432")
        dbname   = os.getenv("DB_NAME", "traxovia_ai")
        user     = os.getenv("DB_USER", "trading_app")
        password = os.getenv("DB_PASSWORD", "")
        conn = psycopg2.connect(host=host, port=port, dbname=dbname,
                                user=user, password=password)
        with conn.cursor() as cur:
            cur.execute("SELECT telegram_bot_token FROM bot_config WHERE id=1")
            row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception as e:
        logger.warning("Could not read token from DB: %s", e)
    return os.getenv("TELEGRAM_BOT_TOKEN", "")


# ── Unknown command fallback ───────────────────────────────────────────────────

async def cmd_unknown(update, context) -> None:
    await update.message.reply_text(
        "❓ Unknown command. Type /help for a list of available commands.",
        parse_mode="HTML",
    )


# ── Bot command menu (shows in Telegram's "/" menu) ───────────────────────────

BOT_COMMANDS = [
    BotCommand("start",         "Welcome and account status"),
    BotCommand("help",          "List all commands by plan tier"),
    BotCommand("link",          "Link your Traxovia AI account"),
    BotCommand("unlink",        "Unlink your account"),
    BotCommand("me",            "Show your account info and plan"),
    BotCommand("status",        "MT5 account status (Starter+)"),
    BotCommand("pnl",           "30-day P&L summary (Starter+)"),
    BotCommand("trades",        "Last 10 closed trades (Starter+)"),
    BotCommand("signals",       "Pending signals (Starter+)"),
    BotCommand("accounts",      "List linked MT5 accounts (Starter+)"),
    BotCommand("risk_state",    "Current risk state (Starter+)"),
    BotCommand("regime",        "Market regime for all pairs (Starter+)"),
    BotCommand("approve",       "Approve a signal (Trader+)"),
    BotCommand("reject",        "Reject a signal (Trader+)"),
    BotCommand("pause",         "Pause automated trading (Trader+)"),
    BotCommand("resume",        "Resume automated trading (Trader+)"),
    BotCommand("bridge_status", "MT5 bridge diagnostics (Trader+)"),
    BotCommand("risk",          "View/update risk parameters (Pro+)"),
    BotCommand("mode",          "Switch trading mode (Pro+)"),
    BotCommand("pairs",         "View or toggle active pairs (Pro+)"),
    BotCommand("setsl",         "Override SL pips for next signal (Pro+)"),
    BotCommand("weekly",        "Weekly confluence bias (Pro+)"),
    BotCommand("dd_override",   "Override drawdown stage (Pro+)"),
    BotCommand("api_key",       "Generate or rotate API key (Elite)"),
]


# ── Approve/reject support /approve <id> and /approve_<id> ───────────────────

async def cmd_approve_prefix(update, context) -> None:
    await cmd_approve(update, context)


async def cmd_reject_prefix(update, context) -> None:
    await cmd_reject(update, context)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    token = _get_token()
    if not token or token == "your-bot-token":
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured.\n"
            "Set it in Admin → Config → Telegram, or add it to .env"
        )

    app = Application.builder().token(token).build()

    # ── Account commands (all users) ──────────────────────────────────────────
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("link",   cmd_link))
    app.add_handler(CommandHandler("unlink", cmd_unlink))
    app.add_handler(CommandHandler("me",     cmd_me))

    # ── Status commands (Starter+) ────────────────────────────────────────────
    app.add_handler(CommandHandler("status",     cmd_status))
    app.add_handler(CommandHandler("pnl",        cmd_pnl))
    app.add_handler(CommandHandler("trades",     cmd_trades))
    app.add_handler(CommandHandler("signals",    cmd_signals))
    app.add_handler(CommandHandler("accounts",   cmd_accounts))
    app.add_handler(CommandHandler("risk_state", cmd_risk_state))
    app.add_handler(CommandHandler("regime",     cmd_regime))

    # ── Trade action commands (Trader+) ───────────────────────────────────────
    app.add_handler(CommandHandler("pause",         cmd_pause))
    app.add_handler(CommandHandler("resume",        cmd_resume))
    app.add_handler(CommandHandler("bridge_status", cmd_bridge_status))

    # approve/reject support both /approve <id> and /approve_<id> patterns
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("reject",  cmd_reject))
    app.add_handler(MessageHandler(
        filters.Regex(r"^/approve_\S+"), cmd_approve_prefix
    ))
    app.add_handler(MessageHandler(
        filters.Regex(r"^/reject_\S+"),  cmd_reject_prefix
    ))

    # ── Pro+ commands ─────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("risk",        cmd_risk))
    app.add_handler(CommandHandler("mode",        cmd_mode))
    app.add_handler(CommandHandler("weekly",      cmd_weekly))
    app.add_handler(CommandHandler("dd_override", cmd_dd_override))
    app.add_handler(CommandHandler("pairs",       cmd_pairs))
    app.add_handler(CommandHandler("setsl",       cmd_setsl))

    # ── Elite commands ────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("api_key", cmd_api_key))

    # ── Catch-all unknown command ─────────────────────────────────────────────
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands(BOT_COMMANDS)
        me = await application.bot.get_me()
        logger.info("Traxovia AI bot started: @%s", me.username)

    app.post_init = post_init

    logger.info("Starting Traxovia AI Telegram bot (polling)…")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
