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

import httpx
from dotenv import load_dotenv

load_dotenv()

from core.execution_engine.mt5_executor import _sign
from database.connection import create_pool, close_pool, get_db_direct

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("paper_loop")

# ── Config ─────────────────────────────────────────────────────────────────────

import uuid

PAIRS    = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30"]
INTERVAL = int(os.getenv("PAPER_LOOP_INTERVAL", "900"))   # 15 min default
TARGET   = int(os.getenv("PAPER_TRADE_TARGET",  "50"))
USER_ID  = str(uuid.uuid5(uuid.NAMESPACE_DNS, "paper-demo-106464235"))  # deterministic UUID

def _bridge_url() -> str:
    return os.getenv("MT5_BRIDGE_PRIMARY_URL", "http://127.0.0.1:8001")

# ── Graceful shutdown ──────────────────────────────────────────────────────────

_shutdown = asyncio.Event()

def _handle_signal(*_):
    logger.info("Shutdown requested — finishing current cycle…")
    _shutdown.set()

# ── Bridge helpers ─────────────────────────────────────────────────────────────

async def _fetch_candles(client: httpx.AsyncClient, symbol: str, timeframe: str) -> list[dict]:
    """Fetch latest candles from MT5 bridge. Returns [] on error."""
    path = f"/ohlc/{symbol}/{timeframe}"
    try:
        resp = await client.get(
            f"{_bridge_url()}{path}",
            params={"count": 200},
            headers=_sign("GET", path),
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get("bars", [])
    except Exception as exc:
        logger.warning("Candle fetch failed %s/%s: %s", symbol, timeframe, exc)
    return []


async def _get_open_positions(client: httpx.AsyncClient) -> list[dict]:
    """Fetch all open positions from MT5 bridge."""
    path = "/positions"
    try:
        resp = await client.get(
            f"{_bridge_url()}{path}",
            headers=_sign("GET", path),
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        logger.warning("Position fetch failed: %s", exc)
    return []

# ── Main cycle ─────────────────────────────────────────────────────────────────

async def run_cycle(stats: dict) -> None:
    """One full paper trading cycle across all pairs."""
    import pandas as pd
    from core.strategy_engine.signal_generator import generate_signal
    from core.execution_engine.mt5_executor import open_order, MT5ExecutorError
    from core.execution_engine.trade_manager import check_open_trades

    async with get_db_direct() as db, httpx.AsyncClient(timeout=30) as client:
        # ── 1. Generate signals ────────────────────────────────────────────
        for symbol in PAIRS:
            if _shutdown.is_set():
                break

            h4_raw, m15_raw = await asyncio.gather(
                _fetch_candles(client, symbol, "H4"),
                _fetch_candles(client, symbol, "M15"),
            )

            if not h4_raw or not m15_raw:
                logger.debug("No candle data for %s — skipping", symbol)
                continue

            htf_df = pd.DataFrame(h4_raw)
            ltf_df = pd.DataFrame(m15_raw)

            try:
                result = await generate_signal(
                    symbol=symbol,
                    htf_df=htf_df,
                    ltf_df=ltf_df,
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
                    sl=result["sl_price"],
                    tp=result["tp_price"],
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
    # Register shutdown handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    await create_pool()

    stats = {"opened": 0, "closed": 0}

    logger.info("=" * 60)
    logger.info("Paper trading loop started")
    logger.info("  Account : #106464235 (demo)")
    logger.info("  Pairs   : %s", ", ".join(PAIRS))
    logger.info("  Interval: %ds (%d min)", INTERVAL, INTERVAL // 60)
    logger.info("  Target  : %d trades", TARGET)
    logger.info("=" * 60)

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

        try:
            await asyncio.wait_for(_shutdown.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass

    await close_pool()
    logger.info("Paper trading loop stopped. Final: %d/%d trades.", stats["closed"], TARGET)


if __name__ == "__main__":
    asyncio.run(main())
