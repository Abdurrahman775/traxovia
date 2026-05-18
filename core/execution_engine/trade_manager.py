"""core/execution_engine/trade_manager.py — SL/TP monitor and trade closer."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

from database.sync_connection import get_sync_db

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False


# ── Pip multipliers ────────────────────────────────────────────────────────────

def _pip_multiplier(pair: str) -> float:
    if "JPY" in pair:
        return 100.0
    if "XAU" in pair or "GOLD" in pair:
        return 10.0
    return 10_000.0


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _sl_tp_hit(trade: dict, bid: float, ask: float) -> str | None:
    direction = trade["direction"]
    sl        = float(trade["stop_loss"])
    tp        = float(trade["take_profit"])
    if direction == "buy":
        if bid >= tp: return "tp"
        if bid <= sl: return "sl"
    else:
        if ask <= tp: return "tp"
        if ask >= sl: return "sl"
    return None


def _compute_pnl(trade: dict, close_price: float) -> tuple[float, float]:
    direction     = trade["direction"]
    entry         = float(trade["entry_price"])
    sl            = float(trade["stop_loss"])
    pair          = trade.get("pair", "EURUSD")
    mult          = _pip_multiplier(pair)
    risk_per_unit = abs(entry - sl)
    if risk_per_unit == 0:
        return 0.0, 0.0
    move  = (close_price - entry) if direction == "buy" else (entry - close_price)
    pnl_r = move / risk_per_unit
    pips  = move * mult
    return round(pnl_r, 4), round(pips, 1)


# ── MT5 direct helpers ─────────────────────────────────────────────────────────

def _get_tick_sync(symbol: str) -> dict | None:
    if not _MT5_AVAILABLE or not mt5.initialize():
        return None
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return {"bid": tick.bid, "ask": tick.ask}


def _close_position_sync(ticket: int) -> float | None:
    if not _MT5_AVAILABLE or not mt5.initialize():
        return None
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return None
    pos        = positions[0]
    close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
    tick       = mt5.symbol_info_tick(pos.symbol)
    price      = tick.bid if pos.type == 0 else tick.ask
    from core.execution_engine.mt5_executor import _get_fill_mode
    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       pos.symbol,
        "volume":       pos.volume,
        "type":         close_type,
        "position":     ticket,
        "price":        price,
        "comment":      "sl_tp_close",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": _get_fill_mode(pos.symbol),
    }
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        return result.price
    return None


# ── DB helpers ─────────────────────────────────────────────────────────────────

def sync_fetchall(conn, sql: str, params: tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _close_trade_in_db(conn, trade: dict, close_price: float, hit: str) -> None:
    pnl_r, pips = _compute_pnl(trade, close_price)
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE trades SET status='closed',
                      exit_time=%s, exit_price=%s, pnl_r=%s, pips=%s,
                      duration_hours=EXTRACT(EPOCH FROM (NOW()-entry_time))/3600
               WHERE id=%s""",
            (datetime.now(timezone.utc), close_price, pnl_r, pips, trade["id"]),
        )
    conn.commit()


# ── Sync loop (Celery task) ────────────────────────────────────────────────────

def check_and_close_positions() -> int:
    with get_sync_db() as conn:
        trades = sync_fetchall(
            conn,
            "SELECT id, user_id, pair, direction, entry_price, stop_loss, take_profit, "
            "lot_size, mt5_ticket, entry_time FROM trades WHERE status='open' AND mt5_ticket IS NOT NULL",
        )

    closed = 0
    for trade in trades:
        try:
            tick = _get_tick_sync(trade["pair"])
            if not tick:
                continue
            hit = _sl_tp_hit(trade, bid=tick["bid"], ask=tick["ask"])
            if not hit:
                continue
            close_price = _close_position_sync(trade["mt5_ticket"])
            if close_price is None:
                close_price = tick["bid"] if trade["direction"] == "buy" else tick["ask"]
            with get_sync_db() as db_conn:
                _close_trade_in_db(db_conn, trade, close_price, hit)
            try:
                from core.ai_engine.feedback_loop import on_trade_closed
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(on_trade_closed(trade["id"], trade["user_id"]))
                finally:
                    loop.close()
            except Exception:
                pass
            closed += 1
        except Exception as e:
            logger.error("Error processing trade %s: %s", trade.get("id"), e)

    return closed


# ── Async loop (paper trading) ─────────────────────────────────────────────────

async def check_open_trades() -> dict:
    from database.connection import get_db_direct

    async with get_db_direct() as db:
        rows = await db.fetch(
            "SELECT id, user_id, pair, direction, entry_price, stop_loss, take_profit, "
            "lot_size, mt5_ticket, entry_time FROM trades WHERE status='open' AND mt5_ticket IS NOT NULL"
        )
        trades = [dict(r) for r in rows]

    checked = len(trades)
    closed  = 0

    for trade in trades:
        try:
            tick = await asyncio.to_thread(_get_tick_sync, trade["pair"])
            if not tick:
                continue
            hit = _sl_tp_hit(trade, bid=tick["bid"], ask=tick["ask"])
            if not hit:
                continue
            close_price = await asyncio.to_thread(_close_position_sync, trade["mt5_ticket"])
            if close_price is None:
                close_price = tick["bid"] if trade["direction"] == "buy" else tick["ask"]
            pnl_r, pips = _compute_pnl(trade, close_price)
            async with get_db_direct() as db:
                await db.execute(
                    "UPDATE trades SET status='closed', exit_price=$1, pnl_r=$2, pips=$3, "
                    "exit_time=NOW() WHERE id=$4",
                    close_price, pnl_r, pips, trade["id"],
                )
            try:
                from core.ai_engine.feedback_loop import on_trade_closed
                await on_trade_closed(trade["id"], trade["user_id"])
            except Exception:
                pass
            closed += 1
        except Exception as e:
            logger.error("Error in check_open_trades for %s: %s", trade.get("id"), e)

    return {"checked": checked, "closed": closed}
