"""
data_engine/realtime_feed.py — Ongoing OHLC candle sync from MT5 (direct).

Called every 15 minutes by the Celery task `update_realtime_feed`.
Keeps ohlc_m15, ohlc_h4, and (on Mondays) ohlc_w1 up to date.

Rules per timeframe:
    M15 — fetch last 3 closed bars every run
    H4  — fetch last 2 closed bars every run
    W1  — fetch last 2 closed bars on Mondays only

Uses MetaTrader5 Python package (Windows only) and psycopg2 via get_sync_db()
for DB writes — both sync, safe inside Celery workers.
"""

import logging
import os
from datetime import datetime, timezone

import psycopg2.extras

from database.sync_connection import get_sync_db

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False

# ── Config ─────────────────────────────────────────────────────────────────────

PAIRS: list[str] = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"]

_M15_COUNT = 3
_H4_COUNT  = 2
_W1_COUNT  = 2

_TF_MAP = {
    "M15": mt5.TIMEFRAME_M15 if _MT5_AVAILABLE else None,
    "H4":  mt5.TIMEFRAME_H4  if _MT5_AVAILABLE else None,
    "W1":  mt5.TIMEFRAME_W1  if _MT5_AVAILABLE else None,
}


# ── Day check ──────────────────────────────────────────────────────────────────

def _is_monday_utc() -> bool:
    return datetime.now(timezone.utc).weekday() == 0


# ── MT5 fetch ──────────────────────────────────────────────────────────────────

def _fetch_bars(symbol: str, timeframe: str, count: int) -> list[dict]:
    if not _MT5_AVAILABLE:
        raise RuntimeError(
            "MetaTrader5 package not installed — deploy on Windows VPS."
        )
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")

    tf    = _TF_MAP[timeframe]
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None:
        raise RuntimeError(
            f"copy_rates_from_pos({symbol}, {timeframe}) failed: {mt5.last_error()}"
        )

    return [
        {
            "time":   int(r["time"]),
            "open":   float(r["open"]),
            "high":   float(r["high"]),
            "low":    float(r["low"]),
            "close":  float(r["close"]),
            "volume": int(r["tick_volume"]),
            "spread": int(r["spread"]),
        }
        for r in rates
    ]


# ── DB upsert ──────────────────────────────────────────────────────────────────

def _posix_to_dt(posix: int) -> datetime:
    return datetime.fromtimestamp(posix, tz=timezone.utc)


def _upsert_bars(
    bars:       list[dict],
    symbol:     str,
    table:      str,
    has_spread: bool,
    conn,
) -> tuple[int, int]:
    if not bars:
        return 0, 0

    if has_spread:
        sql = f"""
            INSERT INTO {table} (time, symbol, open, high, low, close, volume, spread)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (time, symbol) DO NOTHING
        """
        records = [
            (
                _posix_to_dt(b["time"]), symbol,
                float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]),
                int(b["volume"]), int(b.get("spread", 0)),
            )
            for b in bars
        ]
    else:
        sql = f"""
            INSERT INTO {table} (time, symbol, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (time, symbol) DO NOTHING
        """
        records = [
            (
                _posix_to_dt(b["time"]), symbol,
                float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]),
                int(b["volume"]),
            )
            for b in bars
        ]

    inserted = skipped = 0
    with conn.cursor() as cur:
        for record in records:
            cur.execute(sql, record)
            if cur.rowcount == 1:
                inserted += 1
            else:
                skipped += 1

    return inserted, skipped


# ── Public entry point ─────────────────────────────────────────────────────────

def run_realtime_update() -> None:
    if not _MT5_AVAILABLE:
        logger.error("realtime_feed: MetaTrader5 not available — skipping run (Windows VPS required)")
        return

    today_is_monday = _is_monday_utc()

    plan: list[dict] = [
        {"timeframe": "M15", "table": "ohlc_m15", "count": _M15_COUNT, "has_spread": True},
        {"timeframe": "H4",  "table": "ohlc_h4",  "count": _H4_COUNT,  "has_spread": True},
    ]
    if today_is_monday:
        plan.append(
            {"timeframe": "W1", "table": "ohlc_w1", "count": _W1_COUNT, "has_spread": False}
        )

    total_inserted = total_skipped = total_errors = 0

    with get_sync_db() as conn:
        for entry in plan:
            tf         = entry["timeframe"]
            table      = entry["table"]
            count      = entry["count"]
            has_spread = entry["has_spread"]

            for symbol in PAIRS:
                try:
                    bars = _fetch_bars(symbol, tf, count)
                    inserted, skipped = _upsert_bars(bars, symbol, table, has_spread, conn)
                    conn.commit()

                    total_inserted += inserted
                    total_skipped  += skipped

                    if inserted > 0:
                        logger.info(
                            "realtime_feed: %s %-8s — %d fetched  %d inserted  %d skipped",
                            tf, symbol, len(bars), inserted, skipped,
                        )

                except Exception as exc:
                    conn.rollback()
                    total_errors += 1
                    logger.error("realtime_feed: %s %s — %s", tf, symbol, exc)

    logger.info(
        "realtime_feed: complete — %d inserted  %d skipped  %d errors",
        total_inserted, total_skipped, total_errors,
    )
