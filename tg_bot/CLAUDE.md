# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running

```bash
# From project root, with venv active
python -m tg_bot.bot

# Via systemd (production)
sudo systemctl start|stop|restart|status tg_bot
```

The systemd unit file is at `infra/tg_bot.service`. It must **not** use `EnvironmentFile` — `.env` has inline comments that break systemd parsing. `load_dotenv()` in `bot.py` handles `.env` directly.

## Architecture

```
tg_bot/
  bot.py              — entry point: token resolution, handler registration, polling loop
  community_drops.py  — channel broadcast helpers (signals + trade results)
  handlers/
    __init__.py       — shared constants, plan-tier sets, _bot_db(), helpers
    account_handlers.py  — /start /help /link /unlink /me
    status_handlers.py   — /status /pnl /trades /signals /accounts /risk_state /regime
    trade_handlers.py    — /approve /reject /pause /resume
    pro_handlers.py      — /risk /mode /weekly /dd_override /bridge_status /pairs /setsl /api_key
```

### Token Resolution (`bot.py: _get_token`)

1. Connects to DB via psycopg2 and reads `telegram_bot_token` from `bot_config WHERE id=1`
2. Falls back to `TELEGRAM_BOT_TOKEN` env var if DB read fails

The token is **never** hardcoded. Update it through Admin → Config → Telegram in the dashboard.

### Database Connection (`handlers/__init__.py: _bot_db`)

All handlers use the `_bot_db()` async context manager, which opens a **fresh asyncpg connection per command call** and closes it on exit. There is no shared pool in the bot process — each command call connects and disconnects independently.

```python
async with _bot_db() as db:
    row = await db.fetchrow("SELECT ...")
```

### Plan Tiers

Defined in `handlers/__init__.py`:

| Set | Plans included |
|---|---|
| `_STARTER_PLANS` | starter, trader, pro, elite, trial |
| `_TRADER_PLANS` | trader, pro, elite |
| `_PRO_PLANS` | pro, elite |

Every gated command checks the user's plan against the appropriate set and replies with `_upgrade_text()` if access is denied. The `community` plan has no command access — community users only receive channel drops.

### Command Tiers

| Tier | Commands |
|---|---|
| All users | `/start` `/help` `/link` `/unlink` `/me` |
| Starter+ | `/status` `/pnl` `/trades` `/signals` `/accounts` `/risk_state` `/regime` |
| Trader+ | `/approve` `/reject` `/pause` `/resume` `/bridge_status` |
| Pro+ | `/risk` `/mode` `/pairs` `/setsl` `/weekly` `/dd_override` |
| Elite | `/api_key` |

`/approve` and `/reject` support two call patterns: `/approve <signal_id>` (space) and `/approve_<signal_id>` (underscore prefix). Both are wired in `bot.py`.

### Community Drops (`community_drops.py`)

Broadcasts to Telegram channels — not to individual users. Two functions:
- `post_signal_drop(signal)` — sends to `telegram_signals_channel` from `bot_config`
- `post_result_drop(trade, signal)` — sends to `telegram_community_channel` from `bot_config`

Each call reads channel IDs and enabled flags from the DB `bot_config` table, then creates a throwaway `Bot` instance. Drops are silently skipped if the channel ID is empty or the flag is disabled.

Called externally from `notifications/telegram_handler.py` when trades open/close.

## Non-Negotiable Rules

- **All messages use `parse_mode="HTML"`** — never Markdown. Use `<b>`, `<code>`, `<i>`.
- **Bot runs in polling mode** (`run_polling`) — not webhooks. Do not switch to webhooks without updating the systemd unit and reverse proxy.
- **`_bot_db()` opens a fresh connection per call** — do not try to share a connection across handlers or cache it on the context object.
- **Plan gate before any DB query.** Fetch the user row first, check plan, return `_upgrade_text()` early — don't do expensive queries for users who lack access.
- **Token lives in `bot_config` table**, not `.env`. The `.env` value is only a fallback for local dev.
- **No `EnvironmentFile` in the systemd unit** — see above.
