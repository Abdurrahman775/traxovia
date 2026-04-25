"""
feedback_loop.py — Signal Feedback Loop & Auto-Labeling on Trade Close
CORRECTIONS APPLIED:
  [FIX-2] audit_log INSERT had 3 column names but only 2 bind values — the third
          positional param ($3 / detail) was missing. Now passes a meaningful
          detail string: e.g. "trade_closed — win — pnl: 1.4R".
"""

from database.connection import get_db
from scheduler.tasks import trigger_retrain_if_needed


async def on_trade_closed(trade_id: str, user_id: str):
    """
    Called automatically when any trade closes.
    1. Writes labeled outcome to feature_store for next retrain.
    2. Logs action to audit_log.
    3. Drops result to community channel (if signal was community-visible).
    4. Checks whether a model retrain should be triggered.
    """
    db = await get_db()

    # ── Fetch records ────────────────────────────────────────────────
    trade  = await db.fetchrow('SELECT * FROM trades WHERE id=$1', trade_id)
    signal = await db.fetchrow(
        'SELECT * FROM trade_signals WHERE id=$1', trade['signal_id']
    )

    # ── Determine outcome ─────────────────────────────────────────────
    if trade['pnl_r'] > 0.1:
        outcome = 'win'
    elif trade['pnl_r'] < -0.1:
        outcome = 'loss'
    else:
        outcome = 'breakeven'

    # ── Write labeled sample to feature_store ─────────────────────────
    await db.execute(
        '''UPDATE feature_store
           SET outcome=$1, pnl_r=$2, updated_at=NOW()
           WHERE time=$3 AND symbol=$4 AND timeframe=$5''',
        outcome,
        trade['pnl_r'],
        signal['triggered_at'],
        signal['pair'],
        'M15',
    )

    # ── FIX-2: audit_log INSERT now supplies all 3 bind values ─────────
    # Original broken code:
    #   INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)
    #   with only (user_id, outcome) passed → $3 was missing → crash
    #
    # Fixed: construct a meaningful detail string and pass it as $3.
    detail = f'trade_closed — {outcome} — pnl: {trade["pnl_r"]}R — pair: {signal["pair"]}'
    await db.execute(
        'INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)',
        user_id,
        'trade_closed',
        detail,
    )

    # ── Community result drop ──────────────────────────────────────────
    if signal.get('community_visible'):
        await drop_result_to_community(trade, signal)

    # ── Check if retrain is needed ────────────────────────────────────
    await trigger_retrain_if_needed(user_id, db)


async def drop_result_to_community(trade: dict, signal: dict):
    """
    Auto-posts trade result to the community Telegram channel.
    Called from on_trade_closed() for community-visible signals.
    """
    import os
    from telegram import Bot

    emoji      = '✅' if trade['pnl_r'] > 0 else ('❌' if trade['pnl_r'] < 0 else '➖')
    result_str = f'+{trade["pnl_r"]:.1f}R' if trade['pnl_r'] > 0 else f'{trade["pnl_r"]:.1f}R'

    msg = (
        f'{emoji} SIGNAL RESULT — {signal["pair"]}\n'
        f'Direction: {signal["direction"]}\n'
        f'Result: {result_str} ({trade["pips"]:+d} pips)\n'
        f'Duration: {trade["duration_hours"]:.0f}h\n\n'
        f'Full analysis + live signals at tradingai.com'
    )

    bot        = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN'))
    channel_id = os.getenv('TELEGRAM_COMMUNITY_CHANNEL_ID')
    await bot.send_message(channel_id, msg)

    db = await get_db()
    await db.execute(
        'UPDATE community_members SET signals_received = signals_received + 1'
    )
