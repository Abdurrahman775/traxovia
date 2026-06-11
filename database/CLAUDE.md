# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

```
database/
  connection.py          — asyncpg pool + FastAPI dependency (get_db, get_db_direct, set_rls_user)
  sync_connection.py     — psycopg2 helpers for Celery tasks (get_sync_db, sync_execute, sync_fetchall, sync_fetchone)
  migrate.py             — idempotent migrations that run on every app startup
  init_db.py             — one-shot initialisation script (schema → mat views → RLS)
  point_in_time.py       — point-in-time recovery helpers
  schema.sql             — base tables, TimescaleDB hypertables, indexes
  materialized_views.sql — 3 materialized views + unique indexes for CONCURRENT refresh
  rls_policies.sql       — roles, per-table Row-Level Security policies, grants
  migrations/            — standalone SQL files for one-off structural changes
```

## Connection Modules

### The async boundary rule

| Context | Import | Driver |
|---|---|---|
| FastAPI route handlers | `from database.connection import get_db` | asyncpg (async) |
| Non-FastAPI async callers (paper/live trading loops, scripts) | `from database.connection import get_db_direct` | asyncpg (async) |
| Celery task functions | `from database.sync_connection import get_sync_db` | psycopg2 (sync) |

**Never use asyncpg inside a Celery task. Never use psycopg2 inside a FastAPI route.**

### `connection.py` — asyncpg

`create_pool()` / `close_pool()` are called from `main.py`'s lifespan. Pool: min 5, max 20 connections, 30-second command timeout.

**`get_db()`** — FastAPI `Depends()` dependency. Acquires a connection and wraps it in a transaction. The transaction is required for `SET LOCAL` (used by RLS) to scope correctly to the request — when the transaction commits or rolls back, the session variable is cleared.

```python
@router.get("/trades")
async def list_trades(db=Depends(get_db)):
    await set_rls_user(db, user["sub"])   # must call before any user-owned table access
    rows = await db.fetch("SELECT * FROM trades")
```

**`get_db_direct()`** — async context manager for non-FastAPI callers. Same pool, same transaction wrapping.

```python
async with get_db_direct() as db:
    rows = await db.fetch("SELECT * FROM trades WHERE user_id=$1", user_id)
```

**`set_rls_user(conn, user_id)`** — executes `SET LOCAL app.current_user_id = $1` inside the current transaction. Must be called at the top of any route handler that reads or writes user-owned tables (`trades`, `trade_signals`, `risk_state`, `feature_store`, `audit_log`). If omitted, RLS returns zero rows (the safe default — no data leaks, but the handler will silently return empty results).

### `sync_connection.py` — psycopg2

Connection DSN is built from `DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD / DB_SSLMODE` env vars read directly via `os.getenv()`. These are **not** read through `config.py` Settings (which has `extra="ignore"`).

`get_sync_db()` yields a psycopg2 connection with `autocommit=False`. Write operations require an explicit `conn.commit()` inside the `with` block. Exceptions trigger automatic rollback.

Convenience wrappers — use these in Celery tasks instead of raw cursor management:

| Function | Returns | Use for |
|---|---|---|
| `sync_execute(sql, params)` | None | Single-statement writes; auto-commits |
| `sync_fetchall(sql, params)` | `list[dict]` | SELECT returning multiple rows |
| `sync_fetchone(sql, params)` | `dict \| None` | SELECT returning one row |

## Migrations (`migrate.py`)

`run_migrations()` is called automatically on every FastAPI startup (from `main.py` lifespan). All statements use `IF NOT EXISTS` / `ON CONFLICT DO NOTHING` so re-running is safe. Uses asyncpg (runs in the async lifespan, not a Celery task).

**To add a migration:** append a `(description, sql)` tuple to the `MIGRATIONS` list. The description is logged on every startup. The SQL must be idempotent.

Standalone structural changes that can't be made idempotent go in `migrations/` as `.sql` files applied manually via `psql`.

## Database Initialisation (`init_db.py`)

One-shot script for a fresh database. Applies the three SQL files in dependency order, each in its own transaction:

1. `schema.sql` — extensions, tables, hypertables, indexes
2. `materialized_views.sql` — mat views + unique indexes
3. `rls_policies.sql` — roles, RLS policies, grants

```bash
python -m database.init_db   # from project root
```

After running, prints a verification summary: hypertable list, mat view presence, RLS-enabled tables, total table count (expected: 13).

## Schema

### Regular tables

| Table | Purpose | Notes |
|---|---|---|
| `users` | User accounts and settings | `plan` CHECK constraint: community/starter/trader/pro/elite/trial |
| `mt5_accounts` | Linked MT5 broker accounts | UNIQUE on `(user_id, account_number)` |
| `trade_signals` | Generated signals pre-execution | `gate_results` JSONB stores per-gate pass/fail log |
| `trades` | Executed trades (paper + live) | `is_paper` flag distinguishes; never hard-deleted |
| `risk_state` | Per-user daily risk state | UNIQUE on `(user_id, date)`; one row per user per day |
| `audit_log` | Immutable event log | No UPDATE or DELETE policy — rows cannot be changed after insert |
| `model_versions` | XGBoost model registry | Partial UNIQUE index: only one `active = TRUE` row allowed |
| `bridge_state` | MT5 bridge singleton | Single row tracks primary/standby URL, heartbeat, failover count |
| `bot_config` | Telegram bot + branding config | Singleton (id=1 constraint); token stored here, not `.env` |
| `plan_config` | Plan features and pricing | Seeded in `migrate.py`; admin-editable via dashboard |
| `community_channels` | Telegram community channel registry | |
| `refresh_token_jti` | JWT refresh token revocation log | |
| `password_reset_tokens` | Password reset token store | |
| `billing_events` | Stripe webhook idempotency log | `event_id` PRIMARY KEY prevents double-processing |

### TimescaleDB hypertables

| Table | Chunk interval | Rationale |
|---|---|---|
| `ohlc_m15` | 1 month | 96 rows/day per symbol; monthly chunks 3–5× faster range queries |
| `ohlc_h4` | 6 months | 6 rows/day per symbol; 6-month chunks 8–12× faster |
| `ohlc_w1` | 2 years | 1 row/week; no `spread` column (not meaningful at weekly granularity) |
| `feature_store` | 1 month | Same density as M15; `outcome` written NULL at signal time, updated on trade close |

All OHLC tables use `(time, symbol)` as composite primary key and have a `(symbol, time DESC)` lookup index.

To verify hypertables after setup:
```sql
SELECT hypertable_name, chunk_time_interval FROM timescaledb_information.hypertables ORDER BY hypertable_name;
```

## Materialized Views

Three views refreshed every 15 minutes by the `refresh_materialized_views` Celery task:

| View | Key | Drives |
|---|---|---|
| `mv_daily_pnl` | `(user_id, trade_date)` | P&L calendar and daily breakdown widgets |
| `mv_rolling_performance` | `(user_id)` | 30-day headline stats bar (win rate, net R, expectancy) |
| `mv_performance_by_pair` | `(user_id, pair)` | "By Pair" analytics tab |

**Each view has two indexes:** a UNIQUE index (required for `REFRESH MATERIALIZED VIEW CONCURRENTLY`) and a regular lookup index. Dropping the UNIQUE index causes Postgres to silently fall back to a blocking refresh that locks the view for the full query duration. Do not drop them.

## Row-Level Security

Five tables have RLS enabled with `FORCE ROW LEVEL SECURITY` (applies even to the table owner):
`trades`, `trade_signals`, `risk_state`, `feature_store`, `audit_log`

**Mechanism:** FastAPI calls `set_rls_user(conn, user_id)` which sets the session-local `app.current_user_id` variable. The `current_user_id()` SQL function reads it. If the variable is empty, the function returns NULL and all policies evaluate to FALSE — rows are invisible.

**Roles:**
- `trading_app` — application role used by asyncpg connections; subject to all RLS policies
- `trading_admin` — has `BYPASSRLS`; used by migrations, support tooling, and bridge watchdog bulk updates

The `bridge_watchdog` must connect as `trading_admin` when setting `trading_allowed=FALSE` across all users — it has no per-request user context so it cannot set `app.current_user_id`.

**`audit_log` has no UPDATE or DELETE policy** — rows are immutable once written. Any correction requires direct `trading_admin` access.

## Non-Negotiable Rules

- **Async boundary.** asyncpg in FastAPI/async contexts; psycopg2 in Celery tasks. Never mix.
- **`sync_connection.py` reads `DB_*` vars via `os.getenv()`**, not through `config.Settings`. Do not route them through the Settings object.
- **Call `set_rls_user()` before any user-owned table access** in FastAPI routes. Omitting it returns empty results silently, not an error.
- **Trades are never hard-deleted.** No `DELETE` policy exists on `trades`. Use `status = 'cancelled'` instead.
- **`audit_log` rows are immutable.** No UPDATE or DELETE policy by design. Do not add one.
- **`model_versions` enforces a single active model** via a partial unique index on `active = TRUE`. Never manually set two rows to `active = TRUE`.
- **`bot_config` is a singleton** (id=1, CHECK constraint). Never insert a second row; always UPDATE id=1.
- **All migration statements must be idempotent** (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`, etc.). Non-idempotent one-off changes go in `migrations/` and are applied manually.
- **The three unique indexes on materialized views are load-bearing.** Dropping them breaks `CONCURRENT` refresh and causes dashboard-blocking table locks every 15 minutes.
