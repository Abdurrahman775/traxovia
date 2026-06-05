"""
notifications/telegram_handler.py — Telegram notification delivery.

Two flavours:
  sync  — used by Celery workers (psycopg2 + requests, no event loop)
  async — used by FastAPI routes and feedback_loop (asyncpg + httpx)

Public surface:
  notify_admin(msg)                              → sync, admin-only alert
  notify_user_sync(user_id, msg, pref_key)       → sync, respects notification_prefs
  async notify_user(user_id, msg, pref_key, db)  → async, respects notification_prefs
"""
from __future__ import annotations
import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

# ── Token resolution ───────────────────────────────────────────────────────────

def _get_bot_token() -> str:
    """Read token from bot_config DB row first, fall back to env."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "traxovia_ai"),
            user=os.getenv("DB_USER", "trading_app"),
            password=os.getenv("DB_PASSWORD", ""),
        )
        with conn.cursor() as cur:
            cur.execute("SELECT telegram_bot_token, telegram_admin_chat_id FROM bot_config WHERE id=1")
            row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception as e:
        logger.debug("_get_bot_token DB read failed: %s", e)
    return os.getenv("TELEGRAM_BOT_TOKEN", "")


def _get_admin_chat_id() -> str | None:
    """Return the admin Telegram chat_id stored in bot_config."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "traxovia_ai"),
            user=os.getenv("DB_USER", "trading_app"),
            password=os.getenv("DB_PASSWORD", ""),
        )
        with conn.cursor() as cur:
            cur.execute("SELECT telegram_admin_chat_id FROM bot_config WHERE id=1")
            row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return str(row[0])
    except Exception as e:
        logger.debug("_get_admin_chat_id DB read failed: %s", e)
    return os.getenv("TELEGRAM_ADMIN_CHAT_ID")


# ── Low-level sender ───────────────────────────────────────────────────────────

def _send_sync(chat_id: int | str, text: str, token: str) -> bool:
    """Send a message via Telegram Bot API (sync/requests). Returns True on success."""
    if not token or not chat_id:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=8,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning("Telegram send failed (chat %s): %s", chat_id, e)
        return False


# ── Admin notification (sync — safe inside Celery) ────────────────────────────

def notify_admin(msg: str) -> None:
    """Send a plain-text alert to the admin Telegram chat."""
    token   = _get_bot_token()
    chat_id = _get_admin_chat_id()
    if not chat_id:
        logger.warning("notify_admin: no admin chat_id configured")
        return
    _send_sync(chat_id, f"🤖 <b>Traxovia AI</b>\n{msg}", token)


# ── User notification — SYNC (Celery workers) ─────────────────────────────────

def notify_user_sync(user_id: str, msg: str, pref_key: str) -> None:
    """
    Send `msg` to a user via Telegram if:
      1. The user has a telegram_chat_id linked
      2. notification_prefs[pref_key] is true
    Safe to call from Celery workers (uses psycopg2).
    """
    try:
        import psycopg2, psycopg2.extras
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "traxovia_ai"),
            user=os.getenv("DB_USER", "trading_app"),
            password=os.getenv("DB_PASSWORD", ""),
        )
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT telegram_chat_id, notification_prefs FROM users WHERE id=%s::uuid",
                (user_id,),
            )
            row = cur.fetchone()
        conn.close()
    except Exception as e:
        logger.warning("notify_user_sync DB read failed for %s: %s", user_id, e)
        return

    if not row or not row["telegram_chat_id"]:
        return

    prefs = row["notification_prefs"]
    if isinstance(prefs, str):
        try:
            prefs = json.loads(prefs)
        except Exception:
            prefs = {}
    if not prefs.get(pref_key, False):
        return

    token = _get_bot_token()
    _send_sync(row["telegram_chat_id"], msg, token)


# ── User notification — ASYNC (FastAPI / feedback_loop) ───────────────────────

async def notify_user(user_id: str, msg: str, pref_key: str, db) -> None:
    """
    Async version of notify_user_sync.
    `db` is an asyncpg connection or pool-acquired connection.
    Failures are swallowed — notifications are non-critical.
    """
    try:
        row = await db.fetchrow(
            "SELECT telegram_chat_id, notification_prefs FROM users WHERE id=$1::uuid",
            user_id,
        )
        if not row or not row["telegram_chat_id"]:
            return

        prefs = row["notification_prefs"]
        if isinstance(prefs, str):
            try:
                prefs = json.loads(prefs)
            except Exception:
                prefs = {}
        if not prefs.get(pref_key, False):
            return

        chat_id = row["telegram_chat_id"]
        token   = _get_bot_token()

        import httpx
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            )
    except Exception as e:
        logger.warning("notify_user async failed for %s: %s", user_id, e)
