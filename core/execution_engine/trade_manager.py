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
    try:
        from mt5_bridge import client as mt5
        _MT5_AVAILABLE = True
    except Exception:
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

def _get_actual_close_price(ticket: int, entry_time) -> float | None:
    """Look up the actual broker close price from MT5 deal history.

    Called when the position is already gone (auto-closed by broker SL/TP)
    so _close_position_sync returned None. Returns the real fill price instead
    of the stale current tick which would record the wrong P&L.
    """
    if not _MT5_AVAILABLE or not mt5.initialize():
        return None
    from datetime import timedelta
    since = entry_time if hasattr(entry_time, "timestamp") else datetime.now(timezone.utc)
    to    = datetime.now(timezone.utc) + timedelta(hours=1)
    deals = mt5.history_deals_get(since, to) or []
    for d in deals:
        if d.position_id == ticket and d.entry == 1:  # DEAL_ENTRY_OUT
            return float(d.price)
    return None


async def _get_db_tick(pair: str) -> dict | None:
    """Fallback: use latest M15 bar close as bid/ask when MT5 is unavailable."""
    try:
        from database.connection import get_db_direct
        async with get_db_direct() as db:
            row = await db.fetchrow(
                "SELECT close FROM ohlc_m15 WHERE symbol=$1 ORDER BY time DESC LIMIT 1", pair
            )
        if row:
            price = float(row["close"])
            return {"bid": price, "ask": price}
    except Exception:
        pass
    return None


async def check_open_trades(is_paper: bool | None = None) -> dict:
    from database.connection import get_db_direct

    async with get_db_direct() as db:
        if is_paper is None:
            rows = await db.fetch(
                "SELECT id, user_id, pair, direction, entry_price, stop_loss, take_profit, "
                "lot_size, mt5_ticket, entry_time FROM trades WHERE status='open' AND mt5_ticket IS NOT NULL"
            )
        else:
            rows = await db.fetch(
                "SELECT id, user_id, pair, direction, entry_price, stop_loss, take_profit, "
                "lot_size, mt5_ticket, entry_time FROM trades "
                "WHERE status='open' AND mt5_ticket IS NOT NULL AND is_paper=$1",
                is_paper,
            )
        trades = [dict(r) for r in rows]

    checked = len(trades)
    closed  = 0

    for trade in trades:
        try:
            tick = await asyncio.to_thread(_get_tick_sync, trade["pair"])
            if not tick:
                # MT5 unavailable — fall back to latest DB bar price
                tick = await _get_db_tick(trade["pair"])
            if not tick:
                continue
            hit = _sl_tp_hit(trade, bid=tick["bid"], ask=tick["ask"])
            if not hit:
                continue

            # Simulated trades (PAPER_SIM, no real MT5 position) close at the SL/TP price
            is_simulated = not _MT5_AVAILABLE
            if is_simulated:
                close_price = trade["sl_price"] if hit in ("sl", "be_close") else trade["take_profit"]
            else:
                close_price = await asyncio.to_thread(_close_position_sync, trade["mt5_ticket"])
                if close_price is None:
                    # Position already auto-closed by broker — look up actual close price
                    close_price = await asyncio.to_thread(
                        _get_actual_close_price, trade["mt5_ticket"], trade["entry_time"]
                    )
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


# ── SL → Break-even at 1R ──────────────────────────────────────────────────────

def _move_sl_to_be_sync(ticket: int, symbol: str, direction: str, entry_price: float) -> bool:
    """Send a SLTP modify order to move SL to entry (break-even)."""
    if not _MT5_AVAILABLE or not mt5.initialize():
        return False
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return False
    pos = positions[0]
    # Only move SL closer to price, never widen it
    if direction == "buy" and pos.sl >= entry_price:
        return False   # already at or past BE
    if direction == "sell" and pos.sl <= entry_price and pos.sl != 0:
        return False
    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol":   symbol,
        "sl":       entry_price,
        "tp":       pos.tp,
    }
    result = mt5.order_send(request)
    return bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)


async def check_partial_close(is_paper: bool | None = None) -> dict:
    """Move SL to break-even for any open trade that has reached +1R profit.

    Returns {"triggered": <int>} — count of trades where SL was moved to BE.
    Strategy: SL→BE only (no actual partial volume close).
    """
    from database.connection import get_db_direct

    async with get_db_direct() as db:
        if is_paper is None:
            rows = await db.fetch(
                "SELECT id, pair, direction, entry_price, stop_loss, take_profit, "
                "mt5_ticket, partial_closed FROM trades "
                "WHERE status='open' AND mt5_ticket IS NOT NULL AND partial_closed = FALSE"
            )
        else:
            rows = await db.fetch(
                "SELECT id, pair, direction, entry_price, stop_loss, take_profit, "
                "mt5_ticket, partial_closed FROM trades "
                "WHERE status='open' AND mt5_ticket IS NOT NULL AND partial_closed = FALSE AND is_paper=$1",
                is_paper,
            )
        trades = [dict(r) for r in rows]

    triggered = 0

    for trade in trades:
        try:
            tick = await asyncio.to_thread(_get_tick_sync, trade["pair"])
            if not tick:
                # MT5 unavailable — fall back to latest DB bar price
                tick = await _get_db_tick(trade["pair"])
            if not tick:
                continue

            entry  = float(trade["entry_price"])
            sl     = float(trade["stop_loss"])
            risk   = abs(entry - sl)
            if risk == 0:
                continue

            direction = trade["direction"]
            price     = tick["bid"] if direction == "buy" else tick["ask"]
            one_r_price = (entry + risk) if direction == "buy" else (entry - risk)

            # Check if price has reached +1R
            reached = (direction == "buy" and price >= one_r_price) or \
                      (direction == "sell" and price <= one_r_price)
            if not reached:
                continue

            # Move SL to BE on MT5
            moved = await asyncio.to_thread(
                _move_sl_to_be_sync,
                trade["mt5_ticket"], trade["pair"], direction, entry,
            )
            # Mark partial_closed=TRUE in DB so we don't trigger again
            # (even if MT5 is unavailable — prevents repeated attempts)
            async with get_db_direct() as db:
                await db.execute(
                    "UPDATE trades SET partial_closed=TRUE, stop_loss=$1 WHERE id=$2",
                    entry, trade["id"],
                )
            logger.info(
                "%-8s  SL→BE  ticket=%s  entry=%.5f  mt5_moved=%s",
                trade["pair"], trade["mt5_ticket"], entry, moved,
            )
            triggered += 1

        except Exception as e:
            logger.error("Error in check_partial_close for %s: %s", trade.get("id"), e)

    return {"triggered": triggered}
