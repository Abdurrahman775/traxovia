"""
bridge_watchdog.py — MT5 Bridge Watchdog + Hot Standby
CORRECTIONS APPLIED:
  [FIX-1] db was never in scope inside _pause_trading() and _failover_to_standby().
          Each async function now calls `await get_db()` directly.
"""

import os
import httpx
import asyncio
from datetime import datetime
from database.connection import get_db
from notifications.telegram_handler import notify_all_active_users, notify_admin

PRIMARY_URL         = os.getenv('MT5_BRIDGE_URL')
STANDBY_URL         = os.getenv('MT5_BRIDGE_STANDBY_URL')
OFFLINE_PAUSE_SECS  = 120   # 2 minutes → pause new orders
OFFLINE_FAILOVER_SECS = 300  # 5 minutes → promote standby

bridge_state = {
    'active_url':      PRIMARY_URL,
    'last_heartbeat':  datetime.now(),
    'offline_since':   None,
    'trading_paused':  False,
}


async def _persist_state():
    """Write current in-memory bridge_state to the DB so the API can read it."""
    try:
        db = await get_db()
        args = (
            bridge_state['active_url'],
            PRIMARY_URL or 'http://127.0.0.1:8001',
            STANDBY_URL or 'not configured',
            bridge_state['last_heartbeat'],
            bridge_state['offline_since'],
            bridge_state['trading_paused'],
            bridge_state.get('failover_count', 0),
        )
        updated = await db.fetchval(
            """UPDATE bridge_state SET
                   active_url=$1, primary_url=$2, standby_url=$3,
                   last_heartbeat=$4, offline_since=$5,
                   trading_paused=$6, failover_count=$7, updated_at=NOW()
               RETURNING id""",
            *args,
        )
        if not updated:
            await db.execute(
                """INSERT INTO bridge_state
                       (active_url, primary_url, standby_url,
                        last_heartbeat, offline_since, trading_paused, failover_count)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                *args,
            )
    except Exception:
        pass  # Don't let DB write failure break the watchdog loop


async def heartbeat_check():
    """Called every 60 seconds by Celery beat."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f'{bridge_state["active_url"]}/health',
                headers=sign_request("GET", "/health"),
            )
            if resp.status_code == 200:
                bridge_state['last_heartbeat'] = datetime.now()
                bridge_state['offline_since']  = None
                if bridge_state['trading_paused']:
                    await _resume_trading()
                await _persist_state()
                return
    except Exception:
        pass

    # ── Bridge unreachable ──────────────────────────────────────────
    if bridge_state['offline_since'] is None:
        bridge_state['offline_since'] = datetime.now()
        await notify_admin('MT5 Bridge unreachable — monitoring...')

    offline_secs = (datetime.now() - bridge_state['offline_since']).seconds

    if offline_secs >= OFFLINE_PAUSE_SECS and not bridge_state['trading_paused']:
        await _pause_trading()

    if offline_secs >= OFFLINE_FAILOVER_SECS and bridge_state['active_url'] == PRIMARY_URL:
        await _failover_to_standby()

    await _persist_state()


async def _pause_trading():
    """Pause all new orders. Open positions are safe — SL/TP already set at broker."""
    # FIX-1: db initialized here, not assumed from outer scope
    db = await get_db()

    bridge_state['trading_paused'] = True
    await db.execute(
        "UPDATE risk_state SET trading_allowed=FALSE, block_reason='MT5 bridge offline' "
        "WHERE date=CURRENT_DATE"
    )
    await notify_all_active_users(
        'SYSTEM ALERT: MT5 bridge temporarily offline. '
        'New orders paused. Open positions are safe.'
    )
    await notify_admin('CRITICAL: Trading paused — MT5 bridge offline > 2 minutes')


async def _failover_to_standby():
    """Promote standby bridge to primary after 5 minutes offline."""
    # FIX-1: db initialized here, not assumed from outer scope
    db = await get_db()

    bridge_state['active_url'] = STANDBY_URL
    await notify_admin('Failing over to standby bridge...')

    async with httpx.AsyncClient() as client:
        await client.post(
            f'{STANDBY_URL}/mt5/initialize',
            headers=sign_request("POST", "/mt5/initialize"),
        )

    await _resume_trading()
    await notify_admin('Standby bridge promoted — trading resumed')


async def _resume_trading():
    """Re-enable new orders after bridge recovers or standby promoted."""
    # FIX-1: db initialized here, not assumed from outer scope
    db = await get_db()

    bridge_state['trading_paused'] = False
    await db.execute(
        "UPDATE risk_state SET trading_allowed=TRUE, block_reason=NULL "
        "WHERE date=CURRENT_DATE"
    )


# ── HMAC signing (Improvement 3.4) ────────────────────────────────────────────
from core.execution_engine.mt5_executor import _sign as sign_request  # noqa: E402
