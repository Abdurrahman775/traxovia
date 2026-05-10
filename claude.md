# Trading AI SaaS V3 — Claude Code Context

## What This Project Is
A multi-tenant forex trading SaaS platform. Price action strategy (BOS + 
Supply/Demand + Order Blocks) + XGBoost AI + MetaTrader 5 execution.
Full docs in /docx/ folder — read them before writing any code.

## Current Phase
PHASES 1–9 COMPLETE. Platform is in active production.
- 238+ tests passing
- Paper trading live
- Full frontend (React + Vite + Tailwind)
- Admin panel, billing, profile, auth all done
- Telegram bot live as systemd service

## Completed Features
- Auth: Supabase JWT + PostgreSQL RLS
- Billing: Stripe + Paystack (dynamic NGN/USD currency), plan upgrades/downgrades 
  via Subscription.modify() (not new checkout sessions), invoices, usage
- Admin panel: plan management, payment gateway config, user management, rate limiting
- Telegram bot: full command set, running as systemd service (tg_bot.service),
  auto-restarts on crash. Start: `sudo systemctl start tg_bot`
- Paper trading loop (paper_trading_loop.py)
- MT5 bridge (primary + hot standby)
- Notifications system
- Frontend: React 18 + Vite + TanStack Query, deployed at /home/kira/trading-bot/frontend

## Non-Negotiable Architecture Decisions
- Database: TimescaleDB (NOT plain Postgres). Chunk intervals per schema.sql.
- Async: asyncpg for FastAPI routes. psycopg2 for Celery tasks (NEVER mix).
- AI: XGBoost only. Walk-forward validation only (never k-fold).
- Auth: Supabase JWT + PostgreSQL Row-Level Security at DB layer.
- Bridge: Primary + Hot Standby (2 Windows VPS). Never single bridge.

## Critical Rules
- Celery tasks MUST use database/sync_connection.py (get_sync_db)
- FastAPI routes MUST use database/connection.py (get_db / asyncpg)
- Billing downgrades/upgrades use stripe.Subscription.modify() on existing sub,
  NOT a new checkout session — avoids double billing
- Telegram bot token is stored in bot_config table (not .env). bot.py reads DB first.
- tg_bot systemd service must NOT use EnvironmentFile — .env has inline comments
  that break systemd parsing. load_dotenv() in bot.py handles .env correctly.

## Running Services
- API: uvicorn on port 8000 (2 workers), managed by systemd or start_api.sh
- Telegram bot: `sudo systemctl start|stop|status tg_bot`
- Frontend dev: `cd frontend && npm run dev`
- Frontend build output: frontend/dist/

## Tech Stack
Python 3.12 · FastAPI · TimescaleDB · Redis · Celery · XGBoost · 
React 18 · Vite · TanStack Query · Tailwind CSS ·
Stripe · Paystack · Supabase JWT · python-telegram-bot · 
React Native (mobile, future)

## File Structure
- api/          FastAPI routers (billing, auth, profile, admin, etc.)
- tg_bot/       Telegram bot (bot.py + handlers/)
- frontend/     React app (src/pages/, src/api/)
- database/     Migrations, connection helpers, RLS policies
- core/         Trading engine, signal generation
- paper_trading_loop.py  Paper trading daemon
- scripts/      start_api.sh, watchdog_bridge.sh

## What NOT to Do
- Do not use plain PostgreSQL instead of TimescaleDB
- Do not use k-fold cross validation on the AI model
- Do not put asyncpg calls inside Celery tasks
- Do not create a new Stripe checkout session for plan changes when user already
  has an active subscription — use stripe.Subscription.modify() instead
- Do not add EnvironmentFile to tg_bot.service (breaks due to inline comments in .env)
