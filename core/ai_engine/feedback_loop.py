"""core/ai_engine/feedback_loop.py — Auto-labeling on trade close.
FIX-2: audit_log INSERT supplies all 3 bind values.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


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

        # ── Trade execution notification ──────────────────────────────────────
        try:
            from notifications.telegram_handler import notify_user
            pair      = signal["pair"]
            direction = (trade["direction"] or "").upper()
            pnl_sign  = "+" if pnl_r >= 0 else ""
            emoji     = "✅" if pnl_r > 0.05 else ("❌" if pnl_r < -0.05 else "➖")
            tg_msg = (
                f"{emoji} <b>Trade Closed</b>\n"
                f"Pair:  {pair}  {direction}\n"
                f"P&L:   <code>{pnl_sign}{float(pnl_r):.2f}R</code>\n"
                f"Result: {outcome.capitalize()}"
            )
            await notify_user(user_id, tg_msg, "trade_execution", db)
        except Exception as e:
            logger.warning("feedback_loop: trade_execution notify failed: %s", e)

        # ── Re-evaluate drawdown after every trade close ─────────────────────
        # Catches stage escalation from losing trades even when no new
        # signals are being generated.
        try:
            from core.risk_engine.drawdown_monitor import evaluate_drawdown
            await evaluate_drawdown(user_id, db)
        except Exception as e:
            logger.warning("feedback_loop: evaluate_drawdown failed: %s", e)

        if signal.get("community_visible"):
            try:
                from tg_bot.community_drops import post_result_drop
                await post_result_drop(dict(trade), dict(signal))
            except Exception as e:
                logger.warning("feedback_loop: community drop failed: %s", e)

        try:
            await trigger_retrain_if_needed(user_id, db)
        except Exception as e:
            logger.warning("feedback_loop: trigger_retrain_if_needed failed: %s", e)
