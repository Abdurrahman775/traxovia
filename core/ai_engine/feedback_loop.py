"""core/ai_engine/feedback_loop.py — Auto-labeling on trade close.
FIX-2: audit_log INSERT supplies all 3 bind values.
"""
from __future__ import annotations


def get_db_direct():
    """Async context manager for asyncpg — patchable in tests."""
    from database.connection import get_db
    return get_db()


async def trigger_retrain_if_needed(user_id: str, db) -> None:
    try:
        from scheduler.tasks import trigger_retrain_if_needed as _t
        await _t(user_id, db)
    except Exception:
        pass


async def on_trade_closed(trade_id: str, user_id: str) -> None:
    async with get_db_direct() as db:
        trade  = await db.fetchrow("SELECT * FROM trades WHERE id=$1", trade_id)
        signal = await db.fetchrow("SELECT * FROM trade_signals WHERE id=$1", trade["signal_id"])

        pnl_r = trade["pnl_r"] or 0.0
        if pnl_r > 0.1:
            outcome = "win"
        elif pnl_r < -0.1:
            outcome = "loss"
        else:
            outcome = "breakeven"

        await db.execute(
            """UPDATE feature_store
               SET outcome=$1, pnl_r=$2, updated_at=NOW()
               WHERE time=$3 AND symbol=$4 AND timeframe=$5""",
            outcome, trade["pnl_r"],
            signal["triggered_at"], signal["pair"], "M15",
        )

        detail = f"trade_closed — {outcome} — pnl: {pnl_r}R — pair: {signal['pair']}"
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
            user_id, "trade_closed", detail,
        )

        if signal.get("community_visible"):
            try:
                from telegram.community_drops import post_result_drop
                await post_result_drop(dict(trade), dict(signal))
            except Exception:
                pass

        await trigger_retrain_if_needed(user_id, db)
