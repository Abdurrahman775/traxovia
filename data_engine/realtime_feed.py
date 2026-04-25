"""
data_engine/realtime_feed.py — Ongoing OHLC candle sync from MT5 bridge.

Called every 15 minutes by the Celery task `update_realtime_feed` in
scheduler/tasks.py. Keeps ohlc_m15, ohlc_h4, and (on Mondays) ohlc_w1
up to date after the one-shot historical_loader bootstrap.

Rules per timeframe:
    M15 — fetch last 3 closed bars every run  (bridges timing gaps if task was delayed)
    H4  — fetch last 2 closed bars every run
    W1  — fetch last 2 closed bars on Mondays only (weekly bar closes Sunday midnight UTC)

Uses requests (sync) for bridge HTTP calls and psycopg2 via get_sync_db()
for DB writes — both required inside Celery sync workers (no asyncpg, no httpx).
"""

import logging
import os
from datetime import datetime, timezone

import psycopg2.extras
import requests

from database.sync_connection import get_sync_db

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

PAIRS: list[str] = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"]

# Fetch a small look-back window so a delayed task never leaves a gap.
# ON CONFLICT DO NOTHING makes re-inserting already-present bars free.
_M15_COUNT = 3   # covers ~45 min — tolerates one missed run
_H4_COUNT  = 2   # covers ~8 h   — tolerates one missed run
_W1_COUNT  = 2   # last 2 weeks  — safe on late-Monday runs

_BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "").rstrip("/")
_API_KEY    = os.getenv("MT5_BRIDGE_API_KEY", "")
_TIMEOUT    = 10  # seconds — realtime feed must be fast; flag bridge issues early


# ── Day check ──────────────────────────────────────────────────────────────────

def _is_monday_utc() -> bool:
    """W1 bar closes at end of Sunday; the completed bar is available on Monday."""
    return datetime.now(timezone.utc).weekday() == 0  # Monday = 0


# ── Bridge call ────────────────────────────────────────────────────────────────

def _fetch_bars(symbol: str, timeframe: str, count: int) -> list[dict]:
    """
    GET /ohlc/{symbol}/{timeframe}?count=N from the active bridge.
    Returns the list of bar dicts from the JSON response.
    Raises requests.HTTPError or requests.Timeout on failure — caller logs and continues.
    """
    resp = requests.get(
        f"{_BRIDGE_URL}/ohlc/{symbol}/{timeframe}",
        params={"count": count},
        headers={"X-Api-Key": _API_KEY},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["bars"]


# ── DB upsert ──────────────────────────────────────────────────────────────────

def _posix_to_dt(posix: int) -> datetime:
    return datetime.fromtimestamp(posix, tz=timezone.utc)


def _upsert_bars(
    bars:       list[dict],
    symbol:     str,
    table:      str,
    has_spread: bool,
    conn:       "psycopg2.extensions.connection",
) -> tuple[int, int]:
    """
    Upsert bars into the target hypertable using individual execute() calls
    so cursor.rowcount per row gives an exact inserted vs. skipped count.

    ON CONFLICT (time, symbol) DO NOTHING — idempotent; existing rows untouched.
    Returns (inserted, skipped).
    """
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
                _posix_to_dt(b["time"]),
                symbol,
                float(b["open"]),
                float(b["high"]),
                float(b["low"]),
                float(b["close"]),
                int(b["volume"]),
                float(b["spread"]),
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
                _posix_to_dt(b["time"]),
                symbol,
                float(b["open"]),
                float(b["high"]),
                float(b["low"]),
                float(b["close"]),
                int(b["volume"]),
            )
            for b in bars
        ]

    inserted = skipped = 0
    with conn.cursor() as cur:
        for record in records:
            cur.execute(sql, record)
            # rowcount=1 → new row inserted; rowcount=0 → conflict, row skipped
            if cur.rowcount == 1:
                inserted += 1
            else:
                skipped += 1

    return inserted, skipped


# ── Public entry point ─────────────────────────────────────────────────────────

def run_realtime_update() -> None:
    """
    Fetch and upsert the latest closed candles for all pairs and applicable
    timeframes. Called directly by the `update_realtime_feed` Celery task.

    A per-pair failure (bridge timeout, symbol not found) is logged and skipped
    without aborting the rest of the run — partial updates are better than none.
    """
    if not _BRIDGE_URL:
        logger.error("realtime_feed: MT5_BRIDGE_URL not set — skipping run")
        return
    if not _API_KEY:
        logger.error("realtime_feed: MT5_BRIDGE_API_KEY not set — skipping run")
        return

    today_is_monday = _is_monday_utc()

    # Build the run plan for this execution
    plan: list[dict] = [
        {"timeframe": "M15", "table": "ohlc_m15", "count": _M15_COUNT, "has_spread": True},
        {"timeframe": "H4",  "table": "ohlc_h4",  "count": _H4_COUNT,  "has_spread": True},
    ]
    if today_is_monday:
        plan.append(
            {"timeframe": "W1", "table": "ohlc_w1", "count": _W1_COUNT, "has_spread": False}
        )
    else:
        logger.debug("realtime_feed: W1 skipped (not Monday)")

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
                    else:
                        logger.debug(
                            "realtime_feed: %s %-8s — %d fetched  0 inserted (already loaded)",
                            tf, symbol, len(bars),
                        )

                except requests.Timeout:
                    conn.rollback()
                    total_errors += 1
                    logger.warning(
                        "realtime_feed: %s %s — bridge timeout after %ss",
                        tf, symbol, _TIMEOUT,
                    )

                except requests.HTTPError as exc:
                    conn.rollback()
                    total_errors += 1
                    logger.warning(
                        "realtime_feed: %s %s — bridge HTTP %s",
                        tf, symbol, exc.response.status_code,
                    )

                except Exception as exc:
                    conn.rollback()
                    total_errors += 1
                    logger.error(
                        "realtime_feed: %s %s — unexpected error: %s",
                        tf, symbol, exc,
                    )

    logger.info(
        "realtime_feed: complete — %d inserted  %d skipped  %d errors",
        total_inserted, total_skipped, total_errors,
    )
