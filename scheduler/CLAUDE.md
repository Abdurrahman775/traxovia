# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`tasks.py` defines the Celery app, all tasks, and the beat schedule. `beat.py` is a thin re-export used for CLI discovery when running beat separately.

## Running

```bash
# Worker (processes tasks) — --pool=solo required for MT5 single-threaded access
celery -A scheduler.tasks worker --pool=solo --loglevel=info

# Beat (enqueues scheduled tasks)
celery -A scheduler.tasks beat --loglevel=info

# Development only — combined worker+beat (never in production)
celery -A scheduler.beat worker --beat --loglevel=info
```

Both worker and beat run as separate systemd services in production (`traxovia-worker.service`, `traxovia-beat.service`). The schedule state is persisted to `celerybeat-schedule` in the project root.

## Beat Schedule

| Task | Schedule | Purpose |
|---|---|---|
| `update_realtime_feed` | every 15 min | Fetch latest M15/H4 candles from MT5 |
| `refresh_materialized_views` | every 15 min | Refresh `mv_daily_pnl`, `mv_rolling_performance`, `mv_performance_by_pair` |
| `check_all_drawdowns` | every 30 min | Re-evaluate DD stages for all active users |
| `check_news_events` | every 10 min | Alert users 30 min before high-impact news |
| `expire_trials` | daily 00:05 UTC | Downgrade expired trials, revoke demo MT5 bindings |
| `send_daily_pnl_summary` | daily 22:00 UTC | P&L digest to opted-in users |
| `check_feature_drift` | daily 06:00 UTC | SHAP drift check, alert if any feature shifts > 0.05 |
| `retrain_model` | Sunday 02:00 UTC | Walk-forward retrain; deploys only if Sharpe > 1.2 and WR > 50% |

## Task Reference

### `retrain_model`
Calls `WalkForwardTrainer.run()` (252-bar train, 63-bar test, 21-bar step). Deploys the new model only if `oos_sharpe > 1.2` **and** `oos_win_rate > 0.50` **and** beats the current active model. Notifies admin via Telegram in all three cases (deployed / not deployed / failed). Both imports (`WalkForwardTrainer`, `notify_admin`) are lazy — the worker starts cleanly even if those modules are absent.

### `check_feature_drift`
Compares current SHAP feature importances against the 30-day rolling average. Alerts admin if any feature shifts > 0.05. Writes a `feature_drift_check` row to `audit_log` on every run (user_id NULL for system events).

### `refresh_materialized_views`
Refreshes all three materialized views with `REFRESH MATERIALIZED VIEW CONCURRENTLY`. Concurrent refresh requires unique indexes on each view — do not drop those indexes.

### `update_realtime_feed`
Delegates to `data_engine.realtime_feed.run_realtime_update()`. Bound task (`bind=True`) with `max_retries=3`, `default_retry_delay=60s` — failures are retried automatically.

### `expire_trials`
Finds users where `plan = 'trial' AND trial_expires_at < NOW()`. In a single transaction: downgrades plan to `community`, sets `is_paper_mode=FALSE`, deactivates demo MT5 accounts (`account_type='demo'`), writes audit log rows. Then sends a Telegram upgrade prompt to each affected user who has a `telegram_chat_id`.

### `send_daily_pnl_summary`
Respects per-user `notification_prefs.daily_pnl` flag (JSON column). Skips users with no trades today. Sends via `_send_sync` (psycopg2 + requests, no event loop).

### `check_all_drawdowns`
Polls `risk_state` for all users with `total_drawdown_pct > 0` today. Re-classifies each user's DD stage; if the stage has escalated, updates the DB row and sends a `drawdown_warning` Telegram notification. This is the safety net for users who accumulate losses between signal-cycle evaluations. The drawdown thresholds here must stay in sync with `core/risk_engine/drawdown_monitor.py`.

### `check_news_events`
Fetches today's economic calendar from Finnhub (`/api/v1/calendar/economic`). Filters for high-impact events 25–40 minutes away. Uses Redis (`db=2`, key prefix `tbot:news:`, 4-hour TTL) to deduplicate — the same event will not be sent twice even if the task overlaps. Finnhub API key is read from `bot_config.finnhub_api_key` first, then `FINNHUB_API_KEY` env var. Silently exits if no key is configured.

### `trigger_retrain_if_needed` (not a Celery task)
An `async` helper called by `feedback_loop.on_trade_closed()` from the FastAPI async context. Uses asyncpg (not psycopg2). Enqueues `retrain_model.delay()` if ≥ 50 new labeled samples have accumulated since the last retrain.

## Celery Configuration

| Setting | Value | Why |
|---|---|---|
| `broker_url` | `redis://localhost:6379/0` | Tasks queue |
| `result_backend` | `redis://localhost:6379/1` | Task results (separate DB) |
| `task_time_limit` | 600 s | Hard kill after 10 min |
| `task_soft_time_limit` | 540 s | Soft warning at 9 min |
| `worker_prefetch_multiplier` | 1 | One task at a time per worker process — required for MT5 |
| `timezone` | UTC | All schedules in UTC |

## Non-Negotiable Rules

- **All task code is synchronous.** Use `get_sync_db()` / `sync_execute()` / `sync_fetchall()` / `sync_fetchone()` — never asyncpg inside a Celery task. The only async code in this module is `trigger_retrain_if_needed`, which is not a task.
- **`trigger_retrain_if_needed` uses asyncpg** — it is called from the FastAPI async context, not from a task. Do not call it from inside a Celery task.
- **Retrain deployment gates are not negotiable:** Sharpe > 1.2, WR > 50%, and beats current model — all three must pass.
- **`REFRESH MATERIALIZED VIEW CONCURRENTLY`** requires the unique indexes on each view. Never drop them.
- **News deduplication uses Redis db=2.** Do not change the DB index or key prefix without also updating any monitoring that watches for `tbot:news:*` keys.
- **Trial expiry is a transaction.** Plan downgrade, MT5 deactivation, and audit log must all succeed together — do not split them across separate statements outside a `with get_sync_db()` block.
- **`celerybeat-schedule`** in the project root is the persistent schedule state file. Do not delete it in production — beat will lose track of last-run times and may fire tasks immediately on restart.
