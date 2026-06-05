"""
live_trading_loop.py — Continuous live trading loop.

Mirrors paper_trading_loop.py exactly but:
  - Executes on the live MT5 account (no simulation fallback)
  - Persists trades with is_paper=FALSE
  - Runs indefinitely (no trade-count target)
  - Aborts at startup if MT5 is not connected or gates have not passed

Cycle (every INTERVAL seconds):
  1. Fetch latest H4 + M15 candles from MT5 (required — no DB fallback)
  2. Run 7-gate signal_generator — skip if blocked
  3. Execute approved signals on live MT5 account
  4. Monitor open positions — close any that hit SL/TP
  5. Trigger feedback_loop.on_trade_closed() for each closed trade

Run:
    python3 live_trading_loop.py

Stop:
    Ctrl-C  (graceful — finishes current cycle before exiting)

Required env vars:
    LIVE_USER_ID        UUID of the live user row in the users table
    DATABASE_URL        Postgres connection string
    MT5_LOGIN           Live MT5 account number (int)
    MT5_PASSWORD        Live MT5 account password
    MT5_SERVER          Broker server name (e.g. Exness-MT5Real8)

Circuit breakers (same as paper loop, same defaults):
    ROLLING_DD_WINDOW   last N closed trades to inspect  (default 15)
    ROLLING_DD_LIMIT    pause if rolling R ≤ -X          (default 3.0)
    ROLLING_PAUSE_TRADES trades to sit out after trigger  (default 10)
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import uuid
from datetime import datetime, timezone

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False

from database.connection import create_pool, close_pool, get_db_direct
from notifications.telegram_handler import notify_admin

_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "live_trading.log")
os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("live_loop")

# ── Config ─────────────────────────────────────────────────────────────────────

PAIRS    = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD"]
INTERVAL = int(os.getenv("LIVE_LOOP_INTERVAL", "900"))   # 15 min default

# Exness appends 'm' to all symbol names — map canonical → broker name
MT5_SYMBOL = {p: p + "m" for p in PAIRS}

_live_user_id = os.getenv("LIVE_USER_ID", "").strip()
if not _live_user_id:
    logger.critical("LIVE_USER_ID env var is not set. Cannot start live loop.")
    sys.exit(1)
USER_ID = _live_user_id

# Rolling drawdown circuit breaker (same calibration as paper loop)
ROLLING_WINDOW       = int(os.getenv("ROLLING_DD_WINDOW",    "15"))
ROLLING_DD_LIMIT     = float(os.getenv("ROLLING_DD_LIMIT",   "3.0"))
ROLLING_PAUSE_TRADES = int(os.getenv("ROLLING_PAUSE_TRADES", "10"))

# ── Graceful shutdown ──────────────────────────────────────────────────────────

_shutdown = asyncio.Event()

def _handle_signal(*_):
    logger.info("Shutdown requested — finishing current cycle…")
    _shutdown.set()

# ── MT5 startup check ─────────────────────────────────────────────────────────

def _assert_mt5_live() -> str:
    """Initialize MT5 and return the connected account number as a string.

    Exits the process only if MT5 is unavailable. Demo accounts are allowed
    with a warning — trades execute with virtual money. Supports explicit
    credential login when MT5_LOGIN is provided.
    """
    if not _MT5_AVAILABLE:
        logger.critical("MetaTrader5 package not installed. Live loop requires a Windows VPS with MT5.")
        sys.exit(1)

    login    = int(os.getenv("MT5_LOGIN", "0"))
    password = os.getenv("MT5_PASSWORD", "")
    server   = os.getenv("MT5_SERVER", "")

    if login and password and server:
        ok = mt5.initialize(login=login, password=password, server=server)
    else:
        ok = mt5.initialize()

    if not ok:
        logger.critical("mt5.initialize() failed: %s", mt5.last_error())
        sys.exit(1)

    info = mt5.account_info()
    if info is None:
        logger.critical("mt5.account_info() returned None after initialize.")
        mt5.shutdown()
        sys.exit(1)

    if info.trade_mode != mt5.ACCOUNT_TRADE_MODE_REAL:
        logger.warning(
            "MT5 account #%s is a DEMO account (trade_mode=%s). "
            "Trades will use virtual money. Set MT5_LOGIN to switch to a live account.",
            info.login, info.trade_mode,
        )

    return str(info.login)

# ── Candle fetching (MT5 only — no DB fallback for live) ──────────────────────

async def _fetch_candles(symbol: str, timeframe: str) -> list[dict]:
    tf_map = {
        "H4":  mt5.TIMEFRAME_H4,
        "M15": mt5.TIMEFRAME_M15,
    }
    tf = tf_map.get(timeframe)
    if tf is None:
        return []

    if not mt5.initialize():
        logger.error("MT5 connection lost fetching %s/%s", symbol, timeframe)
        return []

    broker_symbol = MT5_SYMBOL.get(symbol, symbol)
    mt5.symbol_select(broker_symbol, True)
    rates = mt5.copy_rates_from_pos(broker_symbol, tf, 0, 200)
    if rates is None:
        logger.warning("copy_rates_from_pos failed %s/%s: %s", symbol, timeframe, mt5.last_error())
        return []

    return [
        {
            "time":   int(r["time"]),
            "open":   float(r["open"]),
            "high":   float(r["high"]),
            "low":    float(r["low"]),
            "close":  float(r["close"]),
            "volume": int(r["tick_volume"]),
        }
        for r in rates
    ]

# ── Main cycle ─────────────────────────────────────────────────────────────────

async def run_cycle(stats: dict) -> None:
    """One full live trading cycle across all pairs."""
    import json as _json
    import pandas as pd
    from core.strategy_engine.signal_generator import generate_signal
    from core.execution_engine.mt5_executor import open_order, MT5ExecutorError
    from core.execution_engine.trade_manager import check_open_trades, check_partial_close

    async with get_db_direct() as db:
        # ── Check bridge_state — /pause from Telegram stops all execution ─────
        bridge = await db.fetchrow("SELECT trading_paused FROM bridge_state LIMIT 1")
        if bridge and bridge["trading_paused"]:
            logger.info("Trading paused via Telegram /pause — skipping cycle")
            return

        # ── Pre-fetch portfolio state for correlation gate ─────────────────────
        open_rows = await db.fetch(
            "SELECT pair, direction FROM trades WHERE user_id=$1 AND status='open' AND is_paper=FALSE",
            USER_ID,
        )
        open_trades = [{"pair": r["pair"], "direction": r["direction"]} for r in open_rows]

        # Daily P&L in R (circuit breaker: stop if -3R on the day)
        daily_pnl_r = await db.fetchval(
            "SELECT COALESCE(SUM(pnl_r),0) FROM trades "
            "WHERE user_id=$1 AND is_paper=FALSE AND status='closed' AND exit_time >= NOW()::date",
            USER_ID,
        ) or 0.0

        if float(daily_pnl_r) <= -3.0:
            logger.warning("Daily loss limit hit (%.2fR) — skipping all signals this cycle", daily_pnl_r)
            return

        # Rolling drawdown circuit breaker
        recent_rows = await db.fetch(
            "SELECT pnl_r FROM trades "
            "WHERE user_id=$1 AND is_paper=FALSE AND status='closed' AND pnl_r IS NOT NULL "
            "ORDER BY exit_time DESC LIMIT $2",
            USER_ID, ROLLING_WINDOW,
        )
        if len(recent_rows) >= ROLLING_WINDOW:
            rolling_r = sum(float(r["pnl_r"]) for r in recent_rows)
            if rolling_r <= -ROLLING_DD_LIMIT:
                trades_since = await db.fetchval(
                    "SELECT COUNT(*) FROM trades "
                    "WHERE user_id=$1 AND is_paper=FALSE AND entry_time > ("
                    "  SELECT exit_time FROM trades "
                    "  WHERE user_id=$1 AND is_paper=FALSE AND status='closed' AND pnl_r IS NOT NULL "
                    "  ORDER BY exit_time DESC LIMIT 1 OFFSET $2"
                    ")",
                    USER_ID, ROLLING_WINDOW - 1,
                )
                if int(trades_since or 0) < ROLLING_PAUSE_TRADES:
                    logger.warning(
                        "Rolling DD circuit breaker active — last %dR over %d trades (limit %.1fR). "
                        "Pausing for %d more new trades.",
                        rolling_r, ROLLING_WINDOW, ROLLING_DD_LIMIT,
                        ROLLING_PAUSE_TRADES - int(trades_since or 0),
                    )
                    return

        # ── 1. Generate signals ────────────────────────────────────────────────
        for symbol in PAIRS:
            if _shutdown.is_set():
                break

            h4_raw, m15_raw = await asyncio.gather(
                _fetch_candles(symbol, "H4"),
                _fetch_candles(symbol, "M15"),
            )

            if not h4_raw or not m15_raw:
                logger.debug("No candle data for %s — skipping", symbol)
                continue

            # Skip if an open live position already exists for this pair
            open_count = await db.fetchval(
                "SELECT COUNT(*) FROM trades WHERE user_id=$1 AND pair=$2 AND status='open' AND is_paper=FALSE",
                USER_ID, symbol,
            )
            if open_count:
                logger.info("%-8s  SKIPPED  already have %d open position(s)", symbol, open_count)
                continue

            htf_df = pd.DataFrame(h4_raw)
            ltf_df = pd.DataFrame(m15_raw)

            try:
                result = await generate_signal(
                    symbol=symbol,
                    htf_df=htf_df,
                    m15_df=ltf_df,
                    user_id=USER_ID,
                    db=db,
                    open_trades=open_trades,
                    daily_pnl_r=float(daily_pnl_r),
                    ltf_df=None,
                )
            except Exception as exc:
                logger.error("Signal generation error %s: %s", symbol, exc)
                continue

            if result.get("signal") != "generated":
                logger.info("%-8s  BLOCKED  gate=%s  %s",
                            symbol, result.get("gate"), result.get("reason", ""))
                continue

            # ── 2. Record signal ───────────────────────────────────────────────
            direction_db = "buy" if result["direction"] == "bullish" else "sell"
            gate_results = {
                k: result[k] for k in ("d1_bias", "fvg_top", "fvg_bottom",
                                       "bias_strength", "zone_strength")
                if result.get(k) is not None
            }
            signal_id = await db.fetchval(
                """INSERT INTO trade_signals
                       (user_id, pair, direction, entry_price, stop_loss, take_profit,
                        lot_size, regime, regime_adx, timeframe, gate_results, status)
                   VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,'M15',$10::jsonb,'approved')
                   RETURNING id""",
                USER_ID,
                symbol,
                direction_db,
                result["entry_price"],
                result["sl_price"],
                result["tp_price"],
                result["lot_size"],
                result.get("regime"),
                result.get("adx"),
                _json.dumps(gate_results) if gate_results else None,
            )

            # ── 3. Execute on live account — no simulation fallback ────────────
            try:
                order = await open_order(
                    symbol=MT5_SYMBOL.get(symbol, symbol),
                    direction=direction_db,
                    lot_size=result["lot_size"],
                    stop_loss=result["sl_price"],
                    take_profit=result["tp_price"],
                    comment="LIVE",
                )
            except MT5ExecutorError as exc:
                logger.error("%-8s  ORDER FAILED — %s (signal not executed)", symbol, exc)
                continue

            stats["opened"] += 1
            logger.info("%-8s  LIVE      ticket=%-10s  dir=%-5s  entry=%.5f  lot=%.2f  [%d opened]",
                        symbol, order.ticket, result["direction"],
                        order.open_price, order.lot_size, stats["opened"])
            notify_admin(
                f"🟢 <b>LIVE TRADE OPENED</b>\n"
                f"Pair:    <code>{symbol}</code>\n"
                f"Dir:     <b>{result['direction'].upper()}</b>\n"
                f"Entry:   <code>{order.open_price:.5f}</code>\n"
                f"SL:      <code>{result['sl_price']:.5f}</code>\n"
                f"TP:      <code>{result['tp_price']:.5f}</code>\n"
                f"Lot:     <code>{order.lot_size:.2f}</code>\n"
                f"Ticket:  <code>{order.ticket}</code>"
            )

            # Persist with is_paper=FALSE
            await db.execute(
                """INSERT INTO trades
                   (user_id, signal_id, mt5_ticket, pair, direction,
                    lot_size, entry_price, stop_loss, take_profit, status, is_paper, entry_time)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'open',FALSE,NOW())
                   ON CONFLICT DO NOTHING""",
                USER_ID,
                signal_id,
                order.ticket,
                symbol,
                direction_db,
                result["lot_size"],
                order.open_price,
                result["sl_price"],
                result["tp_price"],
            )

        # ── 3a. BE stop at +1R ─────────────────────────────────────────────────
        partial_result = await check_partial_close(is_paper=False)
        if partial_result.get("triggered"):
            logger.info("BE stops triggered this cycle: %d", partial_result["triggered"])

        # ── 3b. Monitor + close positions ──────────────────────────────────────
        monitor_result = await check_open_trades(is_paper=False)
        newly_closed   = monitor_result.get("closed", 0)
        stats["closed"] += newly_closed
        if newly_closed:
            logger.info("Positions closed this cycle: %d", newly_closed)
            notify_admin(
                f"🔴 <b>LIVE TRADE CLOSED</b>\n"
                f"Positions closed this cycle: <b>{newly_closed}</b>\n"
                f"Total closed: <b>{stats['closed']}</b>"
            )

    logger.info(
        "── Live trades: %d opened total, %d closed total ──",
        stats["opened"], stats["closed"],
    )


async def main() -> None:
    loop = asyncio.get_running_loop()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _handle_signal)
    except (NotImplementedError, AttributeError):
        signal.signal(signal.SIGINT, lambda s, f: _handle_signal())
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, lambda s, f: _handle_signal())

    # ── MT5 connection check — exits if not live ───────────────────────────────
    account_number = _assert_mt5_live()

    await create_pool()

    logger.info("=" * 60)
    logger.info("LIVE trading loop started")
    logger.info("  Account : #%s (LIVE)", account_number)
    logger.info("  User ID : %s", USER_ID)
    logger.info("  Pairs   : %s", ", ".join(PAIRS))
    logger.info("  Interval: %ds", INTERVAL)
    logger.info("  DD brake: -%sR over last %s trades → pause %s trades",
                ROLLING_DD_LIMIT, ROLLING_WINDOW, ROLLING_PAUSE_TRADES)
    logger.info("=" * 60)

    stats = {"opened": 0, "closed": 0}

    while not _shutdown.is_set():
        cycle_start = datetime.now(timezone.utc)
        logger.info("── Cycle start %s ──", cycle_start.strftime("%Y-%m-%d %H:%M:%S UTC"))

        try:
            await run_cycle(stats)
        except Exception as exc:
            logger.error("Cycle error: %s", exc, exc_info=True)

        if _shutdown.is_set():
            break

        elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        wait    = max(0, INTERVAL - elapsed)
        logger.info("Next cycle in %.0fs", wait)

        deadline = asyncio.get_event_loop().time() + wait
        while not _shutdown.is_set():
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(10.0, remaining))

    await close_pool()
    logger.info("Live trading loop stopped. Totals: %d opened, %d closed.", stats["opened"], stats["closed"])


if __name__ == "__main__":
    asyncio.run(main())
