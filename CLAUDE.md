# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**Traxovia AI** — a multi-tenant forex trading SaaS platform. Strategy: price action (BOS + Supply/Demand + Order Blocks) + XGBoost AI + MetaTrader 5 execution. Phases 1–9 complete; platform is in active production.

## Commands

### Backend
```bash
# Run API (dev — port 8080)
uvicorn main:app --host 0.0.0.0 --port 8080 --reload

# Run API (prod, via systemd or script — port 8000)
bash scripts/start_api.sh

# Run Celery worker (--pool=solo required for MT5 single-threaded access)
celery -A scheduler.tasks worker --pool=solo --loglevel=info

# Run Celery beat scheduler
celery -A scheduler.tasks beat --loglevel=info

# Run all tests
pytest

# Run a single test file
pytest tests/test_phase1.py -v

# Run a specific test
pytest tests/test_phase1.py::test_name -v

# Seed admin user
python scripts/seed_admin.py

# Run live trading daemon (requires LIVE_USER_ID, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER in .env)
python3 live_trading_loop.py
```

### Systemd Services
```bash
sudo systemctl start|stop|restart|status traxovia-api
sudo systemctl start|stop|restart|status traxovia-worker
sudo systemctl start|stop|restart|status traxovia-beat
sudo systemctl start|stop|restart|status tg_bot
```
Unit files live in `infra/` — copy to `/etc/systemd/system/` and run `systemctl daemon-reload` after changes.

### Frontend
```bash
cd frontend && npm run dev      # dev server
cd frontend && npm run build    # production build → frontend/dist/
```

### Database
```bash
# Migrations run automatically on API startup (database/migrate.py)
python database/init_db.py     # manual init if needed
```

## Architecture

### Backend Layers

| Layer | Location | Purpose |
|---|---|---|
| FastAPI app | `main.py` | App entry point, router registration, lifespan (pool + migrations) |
| API routes | `api/routes/` | HTTP endpoints (signals, trades, analytics, admin, billing, news, referral, trial, etc.) |
| Auth | `api/auth.py`, `api/billing.py` | Supabase JWT auth, Stripe/Paystack billing |
| Core engines | `core/` | All trading logic (see below) |
| Data engine | `data_engine/` | Historical loader (CSV + DB), realtime MT5 candle feed, backfill scripts |
| Async DB | `database/connection.py` | asyncpg pool — **FastAPI routes only** |
| Sync DB | `database/sync_connection.py` | psycopg2 — **Celery tasks only** |
| Scheduler | `scheduler/tasks.py` | Celery tasks + beat schedule |
| Paper trading | `paper_trading_loop.py` | Simulated trading daemon (is_paper=TRUE) |
| Live trading | `live_trading_loop.py` | Live MT5 trading daemon (is_paper=FALSE); aborts if MT5 not connected |
| Backtest | `backtest/engine.py` | Offline strategy backtesting |
| Telegram bot | `tg_bot/bot.py` | python-telegram-bot, reads token from `bot_config` DB table |
| Notifications | `notifications/` | Telegram alert handler |

### Core Trading Engines (`core/`)

- **`ai_engine/`** — XGBoost model: feature engineering, training, walk-forward validation, prediction, SHAP analysis, feedback loop
- **`strategy_engine/`** — Signal generation, confluence scoring, bias analysis, entry analysis, FVG/CHoCH/OTE detection, HTF structure, liquidity sweeps, premium/discount zones, RSI divergence, session & news filters
- **`structure_engine/`** — BOS identification, swing detection, zone detection, regime classification, weekly analysis, trend classification
- **`risk_engine/`** — Position sizing, risk management, drawdown monitoring, correlation filtering, spread filtering
- **`execution_engine/`** — MT5 executor, trade manager, copy trade

### Celery Beat Schedule

| Task | Schedule |
|---|---|
| `retrain_model` | Sunday 02:00 UTC |
| `check_feature_drift` | Daily 06:00 UTC |
| `refresh_materialized_views` | Every 15 minutes |
| `update_realtime_feed` | Periodic (M15/H4/W1 candles from MT5) |

### Frontend (`frontend/src/`)

React 18 + Vite + TanStack Query + Tailwind. Structure: `pages/` for route-level views, `components/` for shared UI, `api/` for Axios API calls, `contexts/` for auth/state, `hooks/` for custom hooks. Built output is served by FastAPI as a SPA (catch-all route at the bottom of `main.py`).

## Non-Negotiable Architecture Rules

- **Database**: TimescaleDB (not plain Postgres). Hypertable chunk intervals defined in schema.sql.
- **Async boundary**: asyncpg for FastAPI routes (`get_db`), psycopg2 for Celery tasks (`get_sync_db`). **Never mix.**
- **AI validation**: XGBoost only. Walk-forward validation only — never k-fold.
- **Auth**: Supabase JWT + PostgreSQL Row-Level Security at the DB layer.
- **MT5 bridge**: Primary + Hot Standby (2 Windows VPS). Never single bridge.
- **Celery worker**: Must use `--pool=solo` — MT5 Python API is single-threaded.
- **Billing changes**: Use `stripe.Subscription.modify()` on the existing subscription — never create a new checkout session for plan changes (causes double billing).
- **Telegram bot token**: Stored in `bot_config` DB table, not `.env`. `bot.py` reads DB first.
- **tg_bot.service**: Must NOT use `EnvironmentFile` — `.env` has inline comments that break systemd parsing. `load_dotenv()` in `bot.py` handles it correctly.

## Configuration

All settings in `config.py` via `pydantic_settings.BaseSettings`, loaded from `.env`. Key env vars: `DATABASE_URL`, `REDIS_URL`, `SUPABASE_*`, `JWT_SECRET`, `STRIPE_*`, `TELEGRAM_BOT_TOKEN`.

The `extra="ignore"` setting means `DB_HOST/PORT/NAME/USER/PASSWORD/SSLMODE` are read directly by `sync_connection.py` via `os.getenv()`, not through the Settings object.

## Tests

`pytest.ini` configures `asyncio_mode = auto`. Test files are in `tests/` and `backtest/tests/`. Conftest is at `tests/conftest.py`. The test suite covers each build phase (phase1–phase8) plus MT5 executor, trade manager, rate limiting, and e2e paper trading scenarios.
