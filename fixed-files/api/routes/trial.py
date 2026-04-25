"""
api/routes/trial.py — 14-Day Paper Trading Trial
CORRECTIONS APPLIED:
  [FIX-6] Trial expiry (handled in scheduler/tasks.py expire_trials task) was not
          revoking the demo MT5 account binding. Users kept MT5 access after expiry.
          
          This file handles trial START. The expiry fix lives in scheduler/tasks.py
          (expire_trials task). Both are documented here for cross-reference.

          Changes in this file:
            - On trial start, explicitly sets account_type='demo' on the MT5 binding
              so the expiry task can target it precisely.
            - Adds a clear comment linking to the expiry task.
            - Enforces one-trial-per-account at the DB level with a unique constraint
              recommendation (see comment).
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from database.connection import get_db
from api.auth import get_current_user

router = APIRouter()


@router.post('/trial/start')
async def start_trial(
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Activates a 14-day paper trading trial for a new Community user.
    Requirements:
      - User must be on the 'community' plan (no prior paid plan)
      - Trial can only be started once per account
      - Paper trades execute on a demo MT5 account only
    """
    # ── Guard: only community plan users ──────────────────────────
    if user['plan'] != 'community':
        raise HTTPException(400, 'Trial only available for new Community accounts')

    # ── Guard: one trial per account (check DB, not just state) ───
    # Recommended: add DB constraint:
    #   ALTER TABLE users ADD CONSTRAINT one_trial_per_user
    #     CHECK (trial_expires_at IS NULL OR plan != 'community' OR is_paper_mode = TRUE);
    # The check below is the application-layer guard.
    if user.get('trial_expires_at') is not None:
        raise HTTPException(400, 'Free trial already used — one trial per account')

    expires = datetime.utcnow() + timedelta(days=14)

    await db.execute(
        """UPDATE users
           SET plan='trial',
               trial_expires_at=$1,
               is_paper_mode=TRUE,
               trial_started_at=NOW()
           WHERE id=$2""",
        expires,
        user['id'],
    )

    # ── Log trial start ───────────────────────────────────────────
    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        (user['id'], 'trial_started',
         f'14-day paper trial started — expires {expires.strftime("%Y-%m-%d")}'),
    )

    # ── Create demo MT5 binding (tagged account_type='demo') ──────
    # FIX-6: account_type='demo' is explicitly set here so that the
    # expire_trials() Celery task can target it with:
    #   UPDATE mt5_accounts SET active=FALSE
    #   WHERE user_id = $1 AND account_type = 'demo'
    # Without this tag, the expiry task cannot distinguish demo from live accounts.
    await db.execute(
        """INSERT INTO mt5_accounts(user_id, account_type, active, created_at)
           VALUES($1, 'demo', TRUE, NOW())
           ON CONFLICT (user_id, account_type) DO UPDATE
             SET active=TRUE, created_at=NOW()""",
        user['id'],
    )

    return {
        'trial_expires':  expires.isoformat(),
        'paper_mode':     True,
        'features':       'Full Trader plan features on demo account',
        'note':           (
            'Your trial expires automatically after 14 days. '
            'Your demo MT5 connection will be unlinked at that point. '
            'Subscribe before expiry to keep everything active.'
        ),
    }


@router.get('/trial/status')
async def trial_status(
    user=Depends(get_current_user),
):
    """Returns current trial status and days remaining."""
    if user['plan'] != 'trial' or not user.get('trial_expires_at'):
        return {'active': False}

    days_left = (user['trial_expires_at'] - datetime.utcnow()).days
    return {
        'active':     True,
        'expires_at': user['trial_expires_at'].isoformat(),
        'days_left':  max(0, days_left),
        'paper_mode': user.get('is_paper_mode', True),
    }


# ─── EXPIRY CROSS-REFERENCE ───────────────────────────────────────
# The trial expiry logic (FIX-6 full implementation) lives in:
#   scheduler/tasks.py → expire_trials() Celery task
#
# That task:
#   1. Downgrades plan to 'community'
#   2. Sets is_paper_mode=FALSE
#   3. Sets mt5_accounts.active=FALSE WHERE account_type='demo'  ← FIX-6
#   4. Inserts audit_log entry
#   5. Sends Telegram notification prompting user to subscribe
