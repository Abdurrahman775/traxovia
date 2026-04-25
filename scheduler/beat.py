"""
scheduler/beat.py — Celery Beat entry point.

This module imports the configured Celery app so the beat scheduler can be
launched pointing at this file rather than tasks.py directly. The full beat
schedule is defined in scheduler/tasks.py (app.conf.beat_schedule).

Launch commands
---------------
Worker (processes tasks):
    celery -A scheduler.tasks worker --loglevel=info --concurrency=4

Beat (enqueues scheduled tasks):
    celery -A scheduler.beat beat --loglevel=info --scheduler=celery.beat.PersistentScheduler

Combined (development only — never in production):
    celery -A scheduler.beat worker --beat --loglevel=info

Schedule overview (defined in tasks.py)
-----------------------------------------
Task                        Interval            Phase
refresh_materialized_views  every 15 minutes    1  ← active now
check_bridge_health         every 60 seconds    2  (requires bridge_watchdog)
expire_trials               daily 00:05 UTC     1  ← active now
check_feature_drift         daily 06:00 UTC     6  (requires SHAP modules)
retrain_model               Sunday 02:00 UTC    6  (requires WalkForwardTrainer)
"""

from scheduler.tasks import app  # noqa: F401 — re-exported for celery CLI discovery
