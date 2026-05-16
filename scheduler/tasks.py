"""
scheduler/tasks.py — Celery Task Definitions
CORRECTIONS APPLIED:
  [FIX-4] Original code referenced undefined `db_connection()` and mixed asyncpg
          calls inside sync Celery workers.
          All Celery tasks now use get_sync_db() from database.sync_connection.

Phase notes:
  WalkForwardTrainer and notify_admin are imported lazily inside their functions.
  Both modules are built in later phases (6 and 7). Moving them to lazy imports
  means the Celery worker starts cleanly in Phase 1 without those modules present.
  All task logic is unchanged from the fixed file.
"""

import os

from dotenv import load_dotenv
load_dotenv()

from celery import Celery
from celery.schedules import crontab

from database.sync_connection import get_sync_db, sync_execute, sync_fetchall, sync_fetchone

# ── Celery app ─────────────────────────────────────────────────────────────────

app = Celery('trading_ai')

app.conf.update(
    broker_url=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
    result_backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1'),
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    # Prevent tasks from running indefinitely — hard limit 10 minutes.
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_prefetch_multiplier=1,
)

# ── Beat schedule ──────────────────────────────────────────────────────────────

app.conf.beat_schedule = {
    'weekly-retrain': {
        'task':     'scheduler.tasks.retrain_model',
        'schedule': crontab(hour=2, minute=0, day_of_week=0),  # Sunday 02:00 UTC
    },
    'daily-drift-check': {
        'task':     'scheduler.tasks.check_feature_drift',
        'schedule': crontab(hour=6, minute=0),
    },
    'refresh-mat-views': {
        'task':     'scheduler.tasks.refresh_materialized_views',
        'schedule': crontab(minute='*/15'),
    },
    'realtime-feed': {
        'task':     'scheduler.tasks.update_realtime_feed',
        'schedule': crontab(minute='*/15'),
    },
    'expire-trials': {
        'task':     'scheduler.tasks.expire_trials',
        'schedule': crontab(hour=0, minute=5),   # daily at 00:05 UTC
    },
    'daily-pnl-summary': {
        'task':     'scheduler.tasks.send_daily_pnl_summary',
        'schedule': crontab(hour=22, minute=0),  # daily at 22:00 UTC
    },
    'check-drawdowns': {
        'task':     'scheduler.tasks.check_all_drawdowns',
        'schedule': crontab(minute='*/30'),       # every 30 minutes
    },
    'news-reminders': {
        'task':     'scheduler.tasks.check_news_events',
        'schedule': crontab(minute='*/10'),       # every 10 minutes
    },
}


# ── RETRAIN ────────────────────────────────────────────────────────────────────

@app.task
def retrain_model():
    """
    Weekly walk-forward retraining.
    Deploys only if new model beats all 3 validation gates.
    FIX-4: uses get_sync_db() — no asyncpg inside Celery worker.
    """
    from core.ai_engine.model_trainer import WalkForwardTrainer  # Phase 6
    from notifications.telegram_handler import notify_admin       # Phase 7

    trainer = WalkForwardTrainer(train_window=252, test_window=63, step=21)
    result  = trainer.run()

    if result.oos_sharpe > 1.2 and result.oos_win_rate > 0.50:
        if result.beats_current_model():
            result.deploy()
            notify_admin(f'Model {result.version} deployed — Sharpe: {result.oos_sharpe:.2f}')
        else:
            notify_admin(
                f'Model {result.version} trained but current model is better — not deployed'
            )
    else:
        notify_admin(
            f'Model {result.version} failed validation — '
            f'OOS Sharpe: {result.oos_sharpe:.2f}, OOS WR: {result.oos_win_rate:.1%}'
        )


# ── FEATURE DRIFT CHECK ────────────────────────────────────────────────────────

@app.task
def check_feature_drift():
    """
    Daily SHAP importance drift check.
    Alerts admin if any top feature shifts > 0.05 vs 30-day average.
    FIX-4: uses sync_fetchall() — no asyncpg inside Celery worker.
    """
    from core.ai_engine.shap_utils import (           # Phase 6
        get_current_shap_importance,
        get_shap_importance_30d_avg,
    )
    from notifications.telegram_handler import notify_admin  # Phase 7

    current    = get_current_shap_importance()
    historical = get_shap_importance_30d_avg()
    drifted    = [
        f for f in current
        if abs(current[f] - historical.get(f, 0)) > 0.05
    ]

    if drifted:
        notify_admin(f'Feature drift detected: {drifted} — consider early retrain')

    # Log drift check to audit_log (sync) — user_id is NULL for system events
    sync_execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES(%s,%s,%s)",
        (None, 'feature_drift_check',
         f'drifted={drifted}' if drifted else 'stable'),
    )


# ── MATERIALIZED VIEW REFRESH ──────────────────────────────────────────────────

@app.task
def refresh_materialized_views():
    """
    Runs every 15 minutes. Refreshes all 3 materialized views concurrently.
    FIX-4: uses get_sync_db() — original code referenced undefined db_connection().
    CONCURRENT refresh requires unique indexes on each view (see materialized_views.sql).
    """
    views = [
        'mv_daily_pnl',
        'mv_rolling_performance',
        'mv_performance_by_pair',
    ]
    with get_sync_db() as conn:
        with conn.cursor() as cur:
            for view in views:
                cur.execute(
                    f'REFRESH MATERIALIZED VIEW CONCURRENTLY {view}'
                )
        conn.commit()


# ── TRIAL EXPIRY ───────────────────────────────────────────────────────────────

@app.task
def expire_trials():
    """
    Runs daily at 00:05 UTC.
    Expires 14-day trials and revokes demo MT5 account bindings.

    FIX-6 (applied here too): original code forgot to revoke the demo MT5
    binding on expiry. Users kept MT5 access after trial ended.
    Now also sends a Telegram notification prompting the user to subscribe.
    """
    # Fetch all expired trial users first so we can notify each one
    expired_users = sync_fetchall(
        """
        SELECT id, telegram_chat_id
        FROM users
        WHERE plan = 'trial' AND trial_expires_at < NOW()
        """
    )

    if not expired_users:
        return

    expired_ids = [str(u['id']) for u in expired_users]

    with get_sync_db() as conn:
        with conn.cursor() as cur:
            # 1. Downgrade plan — use ANY with a UUID array (no string interpolation)
            cur.execute(
                "UPDATE users SET plan='community', is_paper_mode=FALSE "
                "WHERE id = ANY(%s::uuid[])",
                (expired_ids,)
            )
            # 2. FIX-6: revoke demo MT5 account binding
            cur.execute(
                "UPDATE mt5_accounts SET active=FALSE "
                "WHERE user_id = ANY(%s::uuid[]) AND account_type='demo'",
                (expired_ids,)
            )
            # 3. Log to audit trail
            for uid in expired_ids:
                cur.execute(
                    "INSERT INTO audit_log(user_id, action, detail) VALUES(%s,%s,%s)",
                    (uid, 'trial_expired', 'Plan reverted to community; demo MT5 unbound'),
                )
        conn.commit()

    # 4. Telegram notification for each expired user
    from notifications.telegram_handler import _get_bot_token, _send_sync
    token = _get_bot_token()
    for user in expired_users:
        if user.get('telegram_chat_id'):
            try:
                _send_sync(
                    user['telegram_chat_id'],
                    '⏰ <b>Your 14-day free trial has ended.</b>\n\n'
                    'Subscribe to keep your signals, dashboard, and MT5 connection.\n\n'
                    'Starter from $29/mo · No setup fees.',
                    token,
                )
            except Exception:
                pass  # User may have blocked the bot — non-fatal


# ── REALTIME FEED ─────────────────────────────────────────────────────────────

@app.task(bind=True, max_retries=3, default_retry_delay=60)
def update_realtime_feed(self):
    """
    Runs every 15 minutes. Fetches the latest closed M15 and H4 candles for
    all 5 pairs from the MT5 bridge and upserts them into TimescaleDB.
    W1 candles are only fetched on Mondays (bar closes Sunday midnight UTC).

    Uses sync DB (psycopg2) and sync HTTP (requests) — no asyncpg in workers.
    Retries up to 3 times on failure with a 60-second delay.
    """
    try:
        from data_engine.realtime_feed import run_realtime_update
        run_realtime_update()
    except Exception as exc:
        raise self.retry(exc=exc)


# ── DAILY P&L SUMMARY ─────────────────────────────────────────────────────────

@app.task
def send_daily_pnl_summary():
    """
    Runs daily at 22:00 UTC.
    Sends each linked user a P&L summary for today if daily_pnl pref is enabled.
    Uses psycopg2 (sync) — safe inside Celery workers.
    """
    from notifications.telegram_handler import _get_bot_token, _send_sync
    import json as _json

    users = sync_fetchall(
        """
        SELECT id, telegram_chat_id, notification_prefs
        FROM users
        WHERE telegram_chat_id IS NOT NULL
          AND plan != 'community'
        """
    )
    token = _get_bot_token()

    for user in users:
        try:
            prefs = user.get("notification_prefs") or {}
            if isinstance(prefs, str):
                prefs = _json.loads(prefs)
            if not prefs.get("daily_pnl", False):
                continue

            stats = sync_fetchone(
                """
                SELECT
                    COUNT(*)                                             AS trades,
                    COALESCE(SUM(pnl_r), 0)                             AS net_r,
                    100.0 * SUM(CASE WHEN pnl_r > 0 THEN 1 ELSE 0 END)
                        / NULLIF(COUNT(*), 0)                           AS win_rate
                FROM trades
                WHERE user_id = %s::uuid
                  AND status = 'closed'
                  AND exit_time >= CURRENT_DATE
                  AND exit_time <  CURRENT_DATE + INTERVAL '1 day'
                """,
                (str(user["id"]),),
            )

            if not stats or not stats["trades"]:
                continue

            net_r    = float(stats["net_r"])
            win_rate = float(stats["win_rate"] or 0)
            emoji    = "✅" if net_r > 0 else ("❌" if net_r < 0 else "➖")
            sign     = "+" if net_r >= 0 else ""

            msg = (
                f"{emoji} <b>Daily P&L Summary</b>\n"
                f"Date:     {__import__('datetime').date.today().strftime('%d %b %Y')}\n"
                f"Trades:   {int(stats['trades'])}\n"
                f"Win rate: {win_rate:.1f}%\n"
                f"Net R:    <code>{sign}{net_r:.2f}R</code>"
            )
            _send_sync(user["telegram_chat_id"], msg, token)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "daily_pnl_summary failed for user %s: %s", user.get("id"), e
            )


# ── PERIODIC DRAWDOWN CHECK ────────────────────────────────────────────────────

@app.task
def check_all_drawdowns():
    """
    Runs every 30 minutes. For every user who has a risk_state row today,
    re-evaluates their drawdown stage and fires a Telegram drawdown_warning
    notification if the stage has escalated.
    Covers users who have losses accumulate between signal generations.
    Uses psycopg2 (sync) — safe inside Celery workers.
    """
    import json as _json
    from notifications.telegram_handler import notify_user_sync

    _DD_CFG = {
        0: {"threshold": 0.0,  "trading_allowed": True,  "block_reason": None},
        1: {"threshold": 10.0, "trading_allowed": True,  "block_reason": "Stage 1: risk capped at 0.5%"},
        2: {"threshold": 12.0, "trading_allowed": True,  "block_reason": "Stage 2: risk capped at 0.25%"},
        3: {"threshold": 15.0, "trading_allowed": False, "block_reason": "Stage 3: trading paused (DD ≥ 15%)"},
    }
    _STAGE_EMOJI = {1: "⚠️", 2: "🚨", 3: "🛑"}

    def _classify(dd_pct):
        if dd_pct >= 15.0: return 3
        if dd_pct >= 12.0: return 2
        if dd_pct >= 10.0: return 1
        return 0

    rows = sync_fetchall(
        """SELECT rs.user_id::text, rs.total_drawdown_pct, rs.drawdown_stage
           FROM risk_state rs
           WHERE rs.date = CURRENT_DATE
             AND rs.total_drawdown_pct > 0"""
    )

    for row in rows:
        try:
            user_id       = row["user_id"]
            dd_pct        = float(row["total_drawdown_pct"] or 0)
            current_stage = int(row["drawdown_stage"] or 0)
            new_stage     = _classify(dd_pct)

            if new_stage == current_stage:
                continue

            cfg = _DD_CFG[new_stage]
            sync_execute(
                """UPDATE risk_state
                   SET drawdown_stage=%s, trading_allowed=%s, block_reason=%s, updated_at=NOW()
                   WHERE user_id=%s::uuid AND date=CURRENT_DATE""",
                (new_stage, cfg["trading_allowed"], cfg["block_reason"], user_id),
            )

            if new_stage >= 1:
                emoji  = _STAGE_EMOJI.get(new_stage, "⚠️")
                status = "Trading <b>PAUSED</b>" if not cfg["trading_allowed"] else "Risk capped"
                msg = (
                    f"{emoji} <b>Drawdown Warning — Stage {new_stage}</b>\n"
                    f"Drawdown: <code>{dd_pct:.2f}%</code>\n"
                    f"Status:   {status}\n"
                    f"{cfg['block_reason'] or ''}"
                )
                notify_user_sync(user_id, msg, "drawdown_warning")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "check_all_drawdowns: failed for user %s: %s", row.get("user_id"), e
            )


# ── NEWS EVENT REMINDERS ────────────────────────────────────────────────────────

@app.task
def check_news_events():
    """
    Runs every 10 minutes. Fetches today's high-impact economic events from
    Finnhub and notifies all users with news_reminder=true, 30 minutes before
    each event fires.

    Deduplication: uses Redis key tbot:news:{event_key} with 4-hour TTL so
    the same event is never sent twice even if task overlaps.

    Finnhub free tier: 60 calls/min — one call every 10 min is well within limits.
    """
    import hashlib
    import json as _json
    from datetime import datetime, timedelta, timezone

    import requests as http
    import redis as _redis

    from notifications.telegram_handler import _get_bot_token, _send_sync

    # Read key from bot_config DB first, fall back to env
    api_key = ""
    row = sync_fetchone("SELECT finnhub_api_key FROM bot_config WHERE id=1")
    if row and row.get("finnhub_api_key"):
        api_key = row["finnhub_api_key"]
    if not api_key:
        api_key = os.getenv("FINNHUB_API_KEY", "")
    if not api_key or api_key == "your-finnhub-api-key":
        return  # not configured yet

    now   = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    # ── Fetch calendar ────────────────────────────────────────────────────────
    try:
        resp = http.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params={"from": today, "to": today, "token": api_key},
            timeout=10,
        )
        if resp.status_code != 200:
            return
        events = resp.json().get("economicCalendar", [])
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("check_news_events: Finnhub fetch failed: %s", e)
        return

    if not events:
        return

    # ── Filter: high-impact, happening in 25–40 min window ───────────────────
    window_start = now + timedelta(minutes=25)
    window_end   = now + timedelta(minutes=40)

    upcoming = []
    for event in events:
        if event.get("impact", "").lower() != "high":
            continue
        time_str = event.get("time", "")
        if not time_str:
            continue
        try:
            # Finnhub returns ISO-8601 with timezone offset
            from datetime import datetime as dt
            event_time = dt.fromisoformat(time_str.replace("Z", "+00:00"))
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
            if window_start <= event_time <= window_end:
                upcoming.append((event, event_time))
        except Exception:
            continue

    if not upcoming:
        return

    # ── Redis dedup ───────────────────────────────────────────────────────────
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        rc = _redis.from_url(redis_url, db=2, decode_responses=True)
    except Exception:
        rc = None

    # ── Get all users with news_reminder=true ─────────────────────────────────
    users = sync_fetchall(
        """SELECT telegram_chat_id, notification_prefs
           FROM users
           WHERE telegram_chat_id IS NOT NULL
             AND plan != 'community'"""
    )
    if not users:
        return

    token = _get_bot_token()

    for event, event_time in upcoming:
        country    = event.get("country", "")
        event_name = event.get("event", "Unknown event")
        time_label = event_time.strftime("%H:%M UTC")
        estimate   = event.get("estimate", "")
        prev       = event.get("prev", "")

        # Build a stable dedup key
        raw_key   = f"{today}:{country}:{event_name}:{event_time.isoformat()}"
        dedup_key = "tbot:news:" + hashlib.md5(raw_key.encode()).hexdigest()

        # Skip if already notified
        if rc:
            if rc.get(dedup_key):
                continue
            rc.setex(dedup_key, 4 * 3600, "1")  # 4-hour TTL

        est_str  = f"Est: {estimate}" if estimate else ""
        prev_str = f"Prev: {prev}"   if prev       else ""
        detail   = "  ".join(filter(None, [est_str, prev_str]))

        msg = (
            f"📰 <b>High-Impact News in ~30 min</b>\n"
            f"🌍 {country}  —  {event_name}\n"
            f"🕐 {time_label}\n"
            + (f"📊 {detail}\n" if detail else "")
            + "\n<i>Consider closing or hedging open positions.</i>"
        )

        for user in users:
            try:
                prefs = user.get("notification_prefs") or {}
                if isinstance(prefs, str):
                    prefs = _json.loads(prefs)
                if not prefs.get("news_reminder", False):
                    continue
                _send_sync(user["telegram_chat_id"], msg, token)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "check_news_events: notify failed for chat %s: %s",
                    user.get("telegram_chat_id"), e,
                )


# ── TRIGGER RETRAIN IF NEEDED ──────────────────────────────────────────────────

async def trigger_retrain_if_needed(user_id: str, db) -> None:
    """
    Called from feedback_loop.on_trade_closed().
    Checks unlabeled sample count and triggers an early retrain if
    50+ new labeled samples have accumulated since last retrain.
    This function is called from an async context (FastAPI) so it uses asyncpg.
    """
    count = await db.fetchval(
        """
        SELECT COUNT(*) FROM feature_store
        WHERE outcome IS NOT NULL
          AND updated_at > (
              SELECT MAX(trained_at) FROM model_versions WHERE active = TRUE
          )
        """
    )
    if count and count >= 50:
        retrain_model.delay()  # enqueue Celery task
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
            user_id, 'retrain_triggered', f'Early retrain: {count} new labeled samples',
        )
