"""
paper_trading_loop.py — Continuous paper trading loop for demo account #106464235.

Cycle (every INTERVAL seconds):
  1. Fetch latest H4 + M15 candles from MT5 bridge for each pair
  2. Run 7-gate signal_generator — skip if blocked
  3. Execute approved signals via mt5_executor (paper/demo account)
  4. Monitor open positions — close any that hit SL/TP
  5. Trigger feedback_loop.on_trade_closed() for each closed trade
  6. Log progress toward 50-trade target

Run:
    python3 paper_trading_loop.py

Stop:
    Ctrl-C  (graceful shutdown after current cycle completes)

Gates required green before live deployment:
  - 50 completed paper trades
  - Win rate ≥ 50 %
  - Max drawdown ≤ 10 %
  - Avg R:R ≥ 1.5
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False

from database.connection import create_pool, close_pool, get_db_direct

_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "paper_trading_err.log")
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
logger = logging.getLogger("paper_loop")

# ── Config ─────────────────────────────────────────────────────────────────────

import uuid

PAIRS    = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD"]
INTERVAL = int(os.getenv("PAPER_LOOP_INTERVAL", "900"))   # 15 min default
TARGET   = int(os.getenv("PAPER_TRADE_TARGET",  "50"))
USER_ID  = str(uuid.uuid5(uuid.NAMESPACE_DNS, "paper-demo-106464235"))  # deterministic UUID

_TF_MAP = {
    "H4":  mt5.TIMEFRAME_H4  if _MT5_AVAILABLE else None,
    "M15": mt5.TIMEFRAME_M15 if _MT5_AVAILABLE else None,
}

# ── Graceful shutdown ──────────────────────────────────────────────────────────

_shutdown = asyncio.Event()

def _handle_signal(*_):
    logger.info("Shutdown requested — finishing current cycle…")
    _shutdown.set()

# ── MT5 direct helpers ─────────────────────────────────────────────────────────

async def _fetch_candles(symbol: str, timeframe: str) -> list[dict]:
    if not _MT5_AVAILABLE or not mt5.initialize():
        logger.warning("MT5 not available — cannot fetch candles for %s/%s", symbol, timeframe)
        return []
    tf    = _TF_MAP.get(timeframe)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, 200)
    if rates is None:
        logger.warning("copy_rates_from_pos failed %s/%s: %s", symbol, timeframe, mt5.last_error())
        return []
    return [
        {"time": int(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
         "low": float(r["low"]), "close": float(r["close"]), "volume": int(r["tick_volume"])}
        for r in rates
    ]


async def _get_open_positions() -> list[dict]:
    if not _MT5_AVAILABLE or not mt5.initialize():
        return []
    positions = mt5.positions_get()
    if positions is None:
        return []
    return [
        {"ticket": p.ticket, "symbol": p.symbol,
         "type": "buy" if p.type == 0 else "sell",
         "volume": p.volume, "price_open": p.price_open, "sl": p.sl, "tp": p.tp}
        for p in positions
    ]

# ── Main cycle ─────────────────────────────────────────────────────────────────

async def run_cycle(stats: dict) -> None:
    """One full paper trading cycle across all pairs."""
    import pandas as pd
    from core.strategy_engine.signal_generator import generate_signal
    from core.execution_engine.mt5_executor import open_order, MT5ExecutorError
    from core.execution_engine.trade_manager import check_open_trades

    async with get_db_direct() as db:
        # ── 1. Generate signals ────────────────────────────────────────────
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

            # Skip if an open paper position already exists for this pair
            open_count = await db.fetchval(
                "SELECT COUNT(*) FROM trades WHERE user_id=$1 AND pair=$2 AND status='open' AND is_paper=TRUE",
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
                )
            except Exception as exc:
                logger.error("Signal generation error %s: %s", symbol, exc)
                continue

            if result.get("signal") != "generated":
                logger.info("%-8s  BLOCKED  gate=%s  %s",
                            symbol, result.get("gate"), result.get("reason", ""))
                continue

            # ── 2. Execute on demo account ─────────────────────────────────
            try:
                order = await open_order(
                    symbol=symbol,
                    direction="buy" if result["direction"] == "bullish" else "sell",
                    lot_size=result["lot_size"],
                    stop_loss=result["sl_price"],
                    take_profit=result["tp_price"],
                    comment="PAPER",
                )
                stats["opened"] += 1
                logger.info("%-8s  OPENED   ticket=%-10s  dir=%-5s  lot=%.2f  [%d opened]",
                            symbol, order.ticket, result["direction"],
                            result["lot_size"], stats["opened"])

                # Persist to DB so trade_manager can monitor it
                await db.execute(
                    """INSERT INTO trades
                       (user_id, signal_id, mt5_ticket, pair, direction,
                        lot_size, entry_price, stop_loss, take_profit, status, is_paper, entry_time)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'open',TRUE,NOW())
                       ON CONFLICT DO NOTHING""",
                    USER_ID,
                    result.get("signal_id"),
                    order.ticket,
                    symbol,
                    "buy" if result["direction"] == "bullish" else "sell",
                    result["lot_size"],
                    order.open_price,
                    result["sl_price"],
                    result["tp_price"],
                )
            except MT5ExecutorError as exc:
                logger.error("%-8s  EXEC ERR  %s", symbol, exc)

        # ── 3. Monitor + close positions ───────────────────────────────────
        monitor_result = await check_open_trades()
        newly_closed   = monitor_result.get("closed", 0)
        stats["closed"] += newly_closed

        if newly_closed:
            logger.info("Positions closed this cycle: %d", newly_closed)

    # ── 4. Progress report ─────────────────────────────────────────────────
    pct = stats["closed"] / TARGET * 100
    logger.info(
        "── Progress: %d/%d trades (%.0f%%)  |  opened_total=%d ──",
        stats["closed"], TARGET, pct, stats["opened"],
    )

    if stats["closed"] >= TARGET:
        logger.info("🎯 TARGET REACHED: %d paper trades complete. Ready for gate review.", TARGET)
        _shutdown.set()


async def main() -> None:
    # Register shutdown handlers (add_signal_handler is Unix-only)
    loop = asyncio.get_running_loop()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _handle_signal)
    except (NotImplementedError, AttributeError):
        signal.signal(signal.SIGINT, lambda s, f: _handle_signal())
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, lambda s, f: _handle_signal())

    await create_pool()

    stats = {"opened": 0, "closed": 0}
    single_shot = os.getenv("PAPER_SINGLE_SHOT", "0").strip() == "1"

    logger.info("=" * 60)
    logger.info("Paper trading cycle started")
    logger.info("  Account : #106464235 (demo)")
    logger.info("  Pairs   : %s", ", ".join(PAIRS))
    logger.info("  Mode    : %s", "single-shot (Task Scheduler)" if single_shot else f"daemon ({INTERVAL}s interval)")
    logger.info("  Target  : %d trades", TARGET)
    logger.info("=" * 60)

    while not _shutdown.is_set():
        cycle_start = datetime.now(timezone.utc)
        logger.info("── Cycle start %s ──", cycle_start.strftime("%Y-%m-%d %H:%M:%S UTC"))

        try:
            await run_cycle(stats)
        except Exception as exc:
            logger.error("Cycle error: %s", exc, exc_info=True)

        # In single-shot mode (Task Scheduler) run one cycle then exit cleanly.
        # Task Scheduler repeats every 15 min — no need to sleep here.
        if single_shot or _shutdown.is_set():
            break

        elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        wait    = max(0, INTERVAL - elapsed)
        logger.info("Next cycle in %.0fs", wait)

        # Sleep in small steps so SIGINT/SIGTERM are handled promptly
        deadline = asyncio.get_event_loop().time() + wait
        while not _shutdown.is_set():
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(10.0, remaining))

    await close_pool()
    logger.info("Paper trading cycle done. Progress: %d/%d trades.", stats["closed"], TARGET)


if __name__ == "__main__":
    asyncio.run(main())
