"""
data_engine/historical_loader.py — One-shot historical OHLC bootstrap.

Fetches historical candle data from the MT5 bridge HTTP API and upserts it
into the TimescaleDB hypertables. Safe to re-run — ON CONFLICT DO NOTHING
means existing rows are never overwritten.

Architecture:
    MT5 Bridge (Windows VPS)
        GET /ohlc/{symbol}/{timeframe}?count=N
                    ↓  httpx async
    historical_loader.py  (Linux VPS — this file)
                    ↓  asyncpg
    TimescaleDB  →  ohlc_m15 / ohlc_h4 / ohlc_w1

Run:
    python3 -m data_engine.historical_loader

Environment variables (read from .env):
    MT5_BRIDGE_URL       — primary bridge base URL, e.g. http://1.2.3.4:8001
    MT5_BRIDGE_API_KEY   — shared API key for X-Api-Key header
    DATABASE_URL         — asyncpg connection string
"""

import asyncio
import os
import sys
import time
from datetime import datetime, timezone

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv()

# ── Load plan ──────────────────────────────────────────────────────────────────
# count is how many bars to request from the bridge.
# W1 requests 104 bars (2 years) for headroom above the 52-week quality gate.
# has_spread mirrors the schema: ohlc_w1 has no spread column.

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"]

LOAD_PLAN: list[dict] = [
    {
        "timeframe":    "M15",
        "table":        "ohlc_m15",
        "count":        8640,       # ≈ 3 months of M15 bars
        "has_spread":   True,
        "label":        "≈ 3 months",
    },
    {
        "timeframe":    "H4",
        "table":        "ohlc_h4",
        "count":        1500,       # ≈ 1 year of H4 bars
        "has_spread":   True,
        "label":        "≈ 1 year",
    },
    {
        "timeframe":    "W1",
        "table":        "ohlc_w1",
        "count":        104,        # 2 years — weekly_analyzer needs ≥ 52
        "has_spread":   False,      # ohlc_w1 has no spread column
        "label":        "≈ 2 years",
    },
]

W1_MIN_BARS = 52        # quality gate checked after loading

INSERT_CHUNK = 1_000    # rows per executemany call

_HR  = "═" * 62
_HR2 = "┄" * 62

# ── Config ─────────────────────────────────────────────────────────────────────

_BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "").rstrip("/")
_API_KEY    = os.getenv("MT5_BRIDGE_API_KEY", "")
_DB_URL     = os.getenv("DATABASE_URL", "")
_TIMEOUT    = 30.0      # seconds — large bar counts take time to serialise


# ── Bridge helpers ─────────────────────────────────────────────────────────────

async def _fetch_ohlc(
    client:    httpx.AsyncClient,
    symbol:    str,
    timeframe: str,
    count:     int,
) -> list[dict]:
    """
    Call GET /ohlc/{symbol}/{timeframe}?count=N on the active bridge.
    Returns the list of bar dicts, or raises on HTTP/network error.
    """
    url = f"{_BRIDGE_URL}/ohlc/{symbol}/{timeframe}"
    resp = await client.get(
        url,
        params={"count": count},
        headers={"X-Api-Key": _API_KEY},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["bars"]


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _to_dt(posix: int) -> datetime:
    """Convert POSIX timestamp (int seconds) to timezone-aware UTC datetime."""
    return datetime.fromtimestamp(posix, tz=timezone.utc)


async def _upsert_bars(
    conn:       asyncpg.Connection,
    table:      str,
    symbol:     str,
    bars:       list[dict],
    has_spread: bool,
) -> int:
    """
    Batch-upsert bars into the target hypertable.
    ON CONFLICT (time, symbol) DO NOTHING — idempotent re-runs.
    Returns the number of rows inserted (conflicts excluded).
    """
    if not bars:
        return 0

    if has_spread:
        sql = f"""
            INSERT INTO {table} (time, symbol, open, high, low, close, volume, spread)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (time, symbol) DO NOTHING
        """
        records = [
            (
                _to_dt(b["time"]),
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
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (time, symbol) DO NOTHING
        """
        records = [
            (
                _to_dt(b["time"]),
                symbol,
                float(b["open"]),
                float(b["high"]),
                float(b["low"]),
                float(b["close"]),
                int(b["volume"]),
            )
            for b in bars
        ]

    inserted = 0
    for i in range(0, len(records), INSERT_CHUNK):
        chunk = records[i : i + INSERT_CHUNK]
        await conn.executemany(sql, chunk)
        inserted += len(chunk)

    return inserted


async def _count_rows(conn: asyncpg.Connection, table: str, symbol: str) -> int:
    return await conn.fetchval(
        f"SELECT COUNT(*) FROM {table} WHERE symbol = $1", symbol
    )


# ── Progress printing ──────────────────────────────────────────────────────────

def _print_row(
    ok:       bool,
    symbol:   str,
    tf:       str,
    received: int | str,
    inserted: int | str,
    note:     str = "",
) -> None:
    mark = "✓" if ok else "✗"
    print(
        f"  {mark}  {symbol:<8} {tf:<4}  "
        f"received {str(received):>5}   inserted {str(inserted):>5}"
        + (f"   {note}" if note else "")
    )


# ── Pre-flight checks ──────────────────────────────────────────────────────────

async def _check_bridge(client: httpx.AsyncClient) -> None:
    """Verify bridge is reachable and MT5 is connected before loading anything."""
    if not _BRIDGE_URL:
        print("ERROR: MT5_BRIDGE_URL is not set in .env", file=sys.stderr)
        sys.exit(1)
    if not _API_KEY:
        print("ERROR: MT5_BRIDGE_API_KEY is not set in .env", file=sys.stderr)
        sys.exit(1)

    try:
        resp = await client.get(
            f"{_BRIDGE_URL}/health",
            headers={"X-Api-Key": _API_KEY},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"ERROR: Bridge not reachable at {_BRIDGE_URL} — {exc}", file=sys.stderr)
        sys.exit(1)

    if not data.get("mt5_connected"):
        print(
            f"ERROR: Bridge is up but MT5 is not connected "
            f"(status={data.get('status')!r}). "
            f"Call POST /mt5/initialize on the bridge first.",
            file=sys.stderr,
        )
        sys.exit(1)

    account = data.get("account", "?")
    balance = data.get("balance", "?")
    standby = " [STANDBY]" if data.get("is_standby") else ""
    print(f"  Bridge OK — account {account}  balance {balance}{standby}")


# ── Main ───────────────────────────────────────────────────────────────────────

async def main() -> None:
    t0 = time.perf_counter()

    # ── Header ──────────────────────────────────────────────────────────────────
    db_display = _DB_URL.split("@")[-1] if "@" in _DB_URL else _DB_URL
    print(_HR)
    print("  Trading AI SaaS V3 — Historical Data Loader")
    print(f"  Bridge : {_BRIDGE_URL}")
    print(f"  DB     : {db_display}")
    print(_HR)

    if not _DB_URL:
        print("ERROR: DATABASE_URL is not set in .env", file=sys.stderr)
        sys.exit(1)

    async with httpx.AsyncClient() as client:
        print()
        await _check_bridge(client)

        conn = await asyncpg.connect(_DB_URL)
        print(f"  DB connected.")
        print()

        results: list[tuple[bool, str, str, int, int]] = []
        # (ok, symbol, timeframe, received, inserted)

        try:
            for plan in LOAD_PLAN:
                tf         = plan["timeframe"]
                table      = plan["table"]
                count      = plan["count"]
                has_spread = plan["has_spread"]
                label      = plan["label"]

                print(_HR2)
                print(f"  {tf}  —  {count} bars per pair ({label})")
                print(_HR2)

                for symbol in PAIRS:
                    try:
                        bars = await _fetch_ohlc(client, symbol, tf, count)
                        received = len(bars)
                        inserted = await _upsert_bars(conn, table, symbol, bars, has_spread)
                        note = "(all already loaded)" if inserted == 0 and received > 0 else ""
                        _print_row(True, symbol, tf, received, inserted, note)
                        results.append((True, symbol, tf, received, inserted))

                    except httpx.HTTPStatusError as exc:
                        msg = f"HTTP {exc.response.status_code}"
                        _print_row(False, symbol, tf, "—", "—", msg)
                        results.append((False, symbol, tf, 0, 0))

                    except Exception as exc:
                        _print_row(False, symbol, tf, "—", "—", str(exc)[:60])
                        results.append((False, symbol, tf, 0, 0))

                print()

            # ── W1 quality gate ────────────────────────────────────────────────
            print(_HR2)
            print(f"  W1 quality gate — minimum {W1_MIN_BARS} weeks per pair")
            print(_HR2)

            w1_ok = True
            for symbol in PAIRS:
                n = await _count_rows(conn, "ohlc_w1", symbol)
                ok = n >= W1_MIN_BARS
                if not ok:
                    w1_ok = False
                mark = "✓" if ok else "✗"
                status = "OK" if ok else f"FAIL (need {W1_MIN_BARS})"
                print(f"  {mark}  {symbol:<8}  {n:>4} weeks   {status}")

            print()

        finally:
            await conn.close()

    # ── Summary ────────────────────────────────────────────────────────────────
    elapsed   = time.perf_counter() - t0
    total_ins = sum(r[4] for r in results)
    succeeded = sum(1 for r in results if r[0])
    total     = len(results)

    print(_HR)
    print(f"  {'✓' if succeeded == total else '✗'}  {succeeded} / {total} loads succeeded")
    print(f"  Total rows inserted : {total_ins:,}")
    print(f"  Elapsed             : {elapsed:.1f}s")
    if not w1_ok:
        print()
        print("  WARNING: W1 quality gate failed for one or more pairs.")
        print("  weekly_analyzer requires ≥ 52 W1 bars — Phase 3 will not work correctly.")
    print(_HR)

    if succeeded < total or not w1_ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
