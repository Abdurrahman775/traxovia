"""
scheduler/tasks.py — Celery Task Definitions
CORRECTIONS APPLIED:
  [FIX-4] Original code referenced undefined `db_connection()` and mixed asyncpg
          calls inside sync Celery workers.
          All Celery tasks now use get_sync_db() from database.sync_connection.
"""

from celery import Celery
from celery.schedules import crontab

from database.sync_connection import get_sync_db, sync_execute, sync_fetchall, sync_fetchone
from core.ai_engine.model_trainer import WalkForwardTrainer
from notifications.telegram_handler import notify_admin

app = Celery('trading_ai')

# ─── SCHEDULE ─────────────────────────────────────────────────────
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
    'bridge-heartbeat': {
        'task':     'scheduler.tasks.check_bridge_health',
        'schedule': 60.0,  # every 60 seconds
    },
    'expire-trials': {
        'task':     'scheduler.tasks.expire_trials',
        'schedule': crontab(hour=0, minute=5),  # daily at 00:05 UTC
    },
}


# ─── RETRAIN ──────────────────────────────────────────────────────
@app.task
def retrain_model():
    """
    Weekly walk-forward retraining.
    Deploys only if new model beats all 3 validation gates.
    FIX-4: uses get_sync_db() — no asyncpg inside Celery worker.
    """
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


# ─── FEATURE DRIFT CHECK ──────────────────────────────────────────
@app.task
def check_feature_drift():
    """
    Daily SHAP importance drift check.
    Alerts admin if any top feature shifts > 0.05 vs 30-day average.
    FIX-4: uses sync_fetchall() — no asyncpg inside Celery worker.
    """
    from core.ai_engine.shap_utils import (
        get_current_shap_importance,
        get_shap_importance_30d_avg,
    )

    current      = get_current_shap_importance()
    historical   = get_shap_importance_30d_avg()
    drifted      = [
        f for f in current
        if abs(current[f] - historical.get(f, 0)) > 0.05
    ]

    if drifted:
        notify_admin(f'Feature drift detected: {drifted} — consider early retrain')

    # Log drift check to audit_log (sync)
    sync_execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        ('system', 'feature_drift_check',
         f'drifted={drifted}' if drifted else 'stable'),
    )


# ─── MATERIALIZED VIEW REFRESH ────────────────────────────────────
@app.task
def refresh_materialized_views():
    """
    Runs every 15 minutes. Refreshes all 3 materialized views concurrently.
    FIX-4: uses get_sync_db() — original code referenced undefined db_connection().
    CONCURRENT refresh requires unique indexes on each view (see schema corrections).
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


# ─── BRIDGE HEARTBEAT ─────────────────────────────────────────────
@app.task
def check_bridge_health():
    """
    Fires every 60 seconds. Delegates to the async heartbeat_check()
    via asyncio.run() — Celery workers have no running event loop.
    """
    import asyncio
    from core.execution_engine.bridge_watchdog import heartbeat_check
    asyncio.run(heartbeat_check())


# ─── TRIAL EXPIRY ─────────────────────────────────────────────────
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
        SELECT id, telegram_id
        FROM users
        WHERE plan = 'trial' AND trial_expires_at < NOW()
        """
    )

    if not expired_users:
        return

    expired_ids = [str(u['id']) for u in expired_users]
    id_list     = ', '.join(f"'{uid}'" for uid in expired_ids)

    with get_sync_db() as conn:
        with conn.cursor() as cur:
            # 1. Downgrade plan
            cur.execute(
                "UPDATE users SET plan='community', is_paper_mode=FALSE "
                f"WHERE id IN ({id_list})"
            )
            # 2. FIX-6: revoke demo MT5 account binding
            cur.execute(
                f"UPDATE mt5_accounts SET active=FALSE "
                f"WHERE user_id IN ({id_list}) AND account_type='demo'"
            )
            # 3. Log to audit trail
            for uid in expired_ids:
                cur.execute(
                    "INSERT INTO audit_log(user_id, action, detail) VALUES(%s,%s,%s)",
                    (uid, 'trial_expired', 'Plan reverted to community; demo MT5 unbound'),
                )
        conn.commit()

    # 4. Telegram notification for each expired user
    import asyncio
    from telegram import Bot
    import os

    async def _notify_expired(users):
        bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN'))
        for user in users:
            if user.get('telegram_id'):
                try:
                    await bot.send_message(
                        user['telegram_id'],
                        '⏰ Your 14-day free trial has ended.\n\n'
                        'Subscribe to keep your signals, dashboard, and MT5 connection:\n'
                        'tradingai.com/billing\n\n'
                        'Starter from $29/mo · No setup fees.',
                    )
                except Exception:
                    pass  # User may have blocked the bot — non-fatal

    asyncio.run(_notify_expired(expired_users))


# ─── TRIGGER RETRAIN IF NEEDED ────────────────────────────────────
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
            (user_id, 'retrain_triggered', f'Early retrain: {count} new labeled samples'),
        )
