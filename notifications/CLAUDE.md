# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`telegram_handler.py` is the single file in this module. It provides Telegram delivery in two flavours — sync (Celery) and async (FastAPI/feedback_loop) — sharing the same token resolution and preference-check logic.

## Public Surface

| Function | Sync/Async | Caller context | Purpose |
|---|---|---|---|
| `notify_admin(msg)` | Sync | Celery tasks | Alert the configured admin chat |
| `notify_user_sync(user_id, msg, pref_key)` | Sync | Celery tasks | Send to a user if preference enabled |
| `notify_user(user_id, msg, pref_key, db)` | Async | FastAPI routes, `feedback_loop` | Send to a user if preference enabled |
| `_send_sync(chat_id, text, token)` | Sync | Internal | Low-level Telegram HTTP send |
| `_get_bot_token()` | Sync | Internal | Read token from `bot_config` or env |
| `_get_admin_chat_id()` | Sync | Internal | Read admin chat ID from `bot_config` or env |

## Token and Admin Chat ID Resolution

Both `_get_bot_token()` and `_get_admin_chat_id()` open a **fresh psycopg2 connection** to read from `bot_config WHERE id=1`, then fall back to env vars (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`) on any error. This means token changes in the admin dashboard take effect on the next notification without a restart.

## Notification Preference Gating

Both `notify_user_sync` and `notify_user` check `users.notification_prefs[pref_key]` before sending. If the pref key is absent or false the message is silently dropped — no error.

Valid `pref_key` values (defined in `migrate.py` default JSONB):

| Key | Triggered by |
|---|---|
| `signal_alerts` | New signal generated |
| `trade_execution` | Trade opened or closed (`feedback_loop`) |
| `daily_pnl` | Daily P&L summary (Celery beat) |
| `drawdown_warning` | Drawdown stage escalation |
| `news_reminder` | High-impact news event approaching |

## Sync vs Async — Which to Call

```
Celery task             → notify_user_sync() / notify_admin()
FastAPI route handler   → notify_user()          (pass the existing asyncpg db)
feedback_loop           → notify_user()          (pass the existing asyncpg db)
drawdown_monitor        → notify_user()          (pass the existing asyncpg db)
check_all_drawdowns     → notify_user_sync()     (Celery worker, no event loop)
```

**Never call `notify_user` (async) from inside a Celery task** — Celery workers have no running event loop. The async version uses `httpx.AsyncClient`; the sync version uses `requests`.

## Failure Behaviour

All functions swallow exceptions and log warnings — notifications are non-critical. A failed send never raises to the caller. This is intentional: a Telegram outage should not interrupt trade execution or signal processing.

## All Messages Use `parse_mode="HTML"`

Format with `<b>`, `<code>`, `<i>` tags. Never use Markdown — the Telegram Bot API parses HTML and Markdown differently and Markdown has more edge-case escaping issues with financial data (asterisks in prices, underscores in pair names).
