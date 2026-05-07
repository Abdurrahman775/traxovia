"""core/execution_engine/trade_manager.py — SL/TP monitor and trade closer."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from database.sync_connection import get_sync_db

logger = logging.getLogger(__name__)

# ── pip multipliers ────────────────────────────────────────────────────────────
_PIP_MULT: dict[str, float] = {}

def _pip_multiplier(pair: str) -> float:
    if "JPY" in pair:
        return 100.0
    if "XAU" in pair or "GOLD" in pair:
        return 10.0
    return 10_000.0


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _sl_tp_hit(trade: dict, bid: float, ask: float) -> str | None:
    direction  = trade["direction"]
    sl         = float(trade["stop_loss"])
    tp         = float(trade["take_profit"])
    if direction == "buy":
        if bid >= tp: return "tp"
        if bid <= sl: return "sl"
    else:  # sell
        if ask <= tp: return "tp"
        if ask >= sl: return "sl"
    return None


def _compute_pnl(trade: dict, close_price: float) -> tuple[float, float]:
    direction   = trade["direction"]
    entry       = float(trade["entry_price"])
    sl          = float(trade["stop_loss"])
    pair        = trade.get("pair", "EURUSD")
    mult        = _pip_multiplier(pair)
    risk_per_unit = abs(entry - sl)
    if risk_per_unit == 0:
        return 0.0, 0.0
    if direction == "buy":
        move = close_price - entry
    else:
        move = entry - close_price
    pnl_r = move / risk_per_unit
    pips  = move * mult
    return round(pnl_r, 4), round(pips, 1)


# ── Sync helpers (used by check_and_close_positions) ──────────────────────────

def sync_fetchall(conn, sql: str, params: tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _get_spread_sync(client, symbol: str) -> dict | None:
    import os, httpx, json
    from core.execution_engine.mt5_executor import _sign
    url  = os.getenv("MT5_BRIDGE_PRIMARY_URL", "http://127.0.0.1:8001")
    path = f"/spread/{symbol}"
    try:
        resp = client.get(f"{url}{path}", headers=_sign("GET", path))
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _close_position_sync(ticket: int) -> dict | None:
    import os, json
    from core.execution_engine.mt5_executor import _sign
    url  = os.getenv("MT5_BRIDGE_PRIMARY_URL", "http://127.0.0.1:8001")
    path = "/order/close"
    body = json.dumps({"ticket": ticket})
    try:
        import httpx
        resp = httpx.post(f"{url}{path}", headers=_sign("POST", path, body), content=body, timeout=10)
        if resp.status_code in (200, 201):
            return resp.json()
    except Exception:
        pass
    return None


def _close_trade_in_db(conn, trade: dict, close_price: float, hit: str) -> None:
    """Write trade close to DB. conn is a psycopg2 connection (caller owns it)."""
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
    """Sync function called by Celery. Returns number of positions closed."""
    import os, httpx
    url = os.getenv("MT5_BRIDGE_PRIMARY_URL", "http://127.0.0.1:8001")

    with get_sync_db() as conn:
        trades = sync_fetchall(
            conn,
            "SELECT id, user_id, pair, direction, entry_price, stop_loss, take_profit, "
            "lot_size, mt5_ticket, entry_time FROM trades WHERE status='open' AND mt5_ticket IS NOT NULL",
        )

    closed = 0
    with httpx.Client(timeout=10) as client:
        for trade in trades:
            try:
                spread = _get_spread_sync(client, trade["pair"])
                if not spread:
                    continue
                hit = _sl_tp_hit(trade, bid=spread["bid"], ask=spread["ask"])
                if not hit:
                    continue
                close_data = _close_position_sync(trade["mt5_ticket"])
                close_price = close_data["close_price"] if close_data else (
                    spread["bid"] if trade["direction"] == "buy" else spread["ask"]
                )
                with get_sync_db() as db_conn:
                    _close_trade_in_db(db_conn, trade, close_price, hit)
                try:
                    from core.ai_engine.feedback_loop import on_trade_closed
                    import asyncio
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

async def _get_spread_async(client, symbol: str) -> dict | None:
    import os
    from core.execution_engine.mt5_executor import _sign
    url  = os.getenv("MT5_BRIDGE_PRIMARY_URL", "http://127.0.0.1:8001")
    path = f"/spread/{symbol}"
    resp = await client.get(f"{url}{path}", headers=_sign("GET", path))
    if resp.status_code == 200:
        return resp.json()
    return None


async def _close_position_async(client, ticket: int) -> dict | None:
    import os, json
    from core.execution_engine.mt5_executor import _sign
    url  = os.getenv("MT5_BRIDGE_PRIMARY_URL", "http://127.0.0.1:8001")
    path = "/order/close"
    body = json.dumps({"ticket": ticket})
    resp = await client.post(f"{url}{path}", headers=_sign("POST", path, body), content=body)
    if resp.status_code in (200, 201):
        return resp.json()
    return None


def get_db_direct():
    """Returns async context manager for asyncpg pool — used by async trade manager."""
    from database.connection import get_db
    return get_db()


async def check_open_trades() -> dict:
    """Async version used by paper trading loop."""
    import httpx
    from database.connection import get_db

    async with get_db_direct() as db:
        rows = await db.fetch(
            "SELECT id, user_id, pair, direction, entry_price, stop_loss, take_profit, "
            "lot_size, mt5_ticket, entry_time FROM trades WHERE status='open' AND mt5_ticket IS NOT NULL"
        )
        trades = [dict(r) for r in rows]

    checked = len(trades)
    closed  = 0

    async with httpx.AsyncClient(timeout=10) as client:
        for trade in trades:
            try:
                spread = await _get_spread_async(client, trade["pair"])
                if not spread:
                    continue
                hit = _sl_tp_hit(trade, bid=spread["bid"], ask=spread["ask"])
                if not hit:
                    continue
                close_data  = await _close_position_async(client, trade["mt5_ticket"])
                close_price = close_data["close_price"] if close_data else (
                    spread["bid"] if trade["direction"] == "buy" else spread["ask"]
                )
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
