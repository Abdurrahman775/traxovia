#!/usr/bin/env python3
"""
scripts/download_m5_and_refresh.py

1. Download M5 data for USDJPY + XAUUSD from Dukascopy (1 year back)
2. Gap-fill H4 + M15 for USDJPY + XAUUSD (last 5 days via yfinance)

Run:
    source venv/bin/activate
    python3 scripts/download_m5_and_refresh.py
"""
from __future__ import annotations

import asyncio
import io
import lzma
import os
import struct
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

PAIRS = ["USDJPY", "XAUUSD"]
M5_MONTHS_BACK = 72    # 6 years — matches H4 + M15 history
BASE_URL       = "https://datafeed.dukascopy.com/datafeed"
RETRY_COUNT    = 3
RETRY_DELAY    = 2.0

STRUCT_FMT  = ">IIIIIf"
RECORD_SIZE = struct.calcsize(STRUCT_FMT)

PRICE_DIVISOR: dict[str, float] = {
    "USDJPY": 1_000.0,
    "XAUUSD": 1_000.0,
}

DUKASCOPY_SYMBOL: dict[str, str] = {
    "USDJPY": "USDJPY",
    "XAUUSD": "XAUUSD",
}

YF_SYMBOL: dict[str, str] = {
    "USDJPY": "USDJPY=X",
    "XAUUSD": "GC=F",
}


# ── Dukascopy 1-min fetcher ────────────────────────────────────────────────────

def _fetch_day_1min(duk_sym: str, d: date, divisor: float) -> pd.DataFrame:
    url = f"{BASE_URL}/{duk_sym}/{d.year}/{d.month-1:02d}/{d.day:02d}/BID_candles_min_1.bi5"
    for attempt in range(RETRY_COUNT):
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 404:
                return pd.DataFrame()
            r.raise_for_status()
            data = lzma.decompress(r.content)
            n = len(data) // RECORD_SIZE
            rows = []
            for i in range(n):
                chunk = data[i * RECORD_SIZE:(i + 1) * RECORD_SIZE]
                secs, o, h, l, c, v = struct.unpack(STRUCT_FMT, chunk)
                ts = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(seconds=secs)
                rows.append({
                    "time":   ts,
                    "open":   o / divisor,
                    "high":   h / divisor,
                    "low":    l / divisor,
                    "close":  c / divisor,
                    "volume": max(0, int(v)),
                })
            return pd.DataFrame(rows)
        except Exception:
            if attempt < RETRY_COUNT - 1:
                time.sleep(RETRY_DELAY)
    return pd.DataFrame()


def _resample_to_m5(df_1m: pd.DataFrame) -> pd.DataFrame:
    if df_1m.empty:
        return pd.DataFrame()
    df_1m = df_1m.set_index("time").sort_index()
    df_5m = df_1m.resample("5min").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["open"])
    return df_5m.reset_index()


# ── DB insert ─────────────────────────────────────────────────────────────────

async def _insert_bars(conn, table: str, symbol: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    records = [
        (row["time"], symbol,
         float(row["open"]), float(row["high"]),
         float(row["low"]),  float(row["close"]),
         int(row["volume"]))
        for _, row in df.iterrows()
    ]
    await conn.executemany(
        f"""INSERT INTO {table} (time, symbol, open, high, low, close, volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (time, symbol) DO NOTHING""",
        records,
    )
    return len(records)


# ── M5 download ───────────────────────────────────────────────────────────────

async def download_m5(conn) -> None:
    today     = date.today()
    start     = today - timedelta(days=M5_MONTHS_BACK * 30)

    for pair in PAIRS:
        duk_sym = DUKASCOPY_SYMBOL[pair]
        divisor = PRICE_DIVISOR[pair]

        existing = await conn.fetchval(
            "SELECT MAX(time)::date FROM ohlc_m5 WHERE symbol=$1", pair
        )
        fetch_from = existing + timedelta(days=1) if existing else start
        days_needed = (today - fetch_from).days

        if days_needed <= 0:
            print(f"  {pair} M5 — already up to date ({existing})")
            continue

        print(f"  {pair} M5 — fetching {days_needed} days from {fetch_from} …", flush=True)
        total = 0
        d = fetch_from
        while d < today:
            if d.weekday() < 5:  # skip weekends
                df_1m = _fetch_day_1min(duk_sym, d, divisor)
                df_5m = _resample_to_m5(df_1m)
                n = await _insert_bars(conn, "ohlc_m5", pair, df_5m)
                total += n
            d += timedelta(days=1)

        print(f"    → {total} M5 bars inserted for {pair}")


# ── H4 + M15 gap-fill via yfinance ────────────────────────────────────────────

async def refresh_h4_m15(conn) -> None:
    for pair in PAIRS:
        yf_sym = YF_SYMBOL[pair]
        print(f"  {pair} H4/M15 gap-fill via yfinance …", flush=True)

        try:
            ticker = yf.Ticker(yf_sym)
            df = ticker.history(period="10d", interval="1h", auto_adjust=True)
            if df.empty:
                print(f"    No data from yfinance for {pair}")
                continue

            df = df.reset_index()
            col = "Datetime" if "Datetime" in df.columns else "index"
            df.rename(columns={col: "time", "Open": "open", "High": "high",
                                "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df[["time", "open", "high", "low", "close", "volume"]].sort_values("time")
            df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].astype(float)
            df["volume"] = df["volume"].fillna(0).astype(int)

            # Aggregate 1h → H4
            df_idx = df.set_index("time")
            df_h4 = df_idx.resample("4h").agg(
                open=("open","first"), high=("high","max"),
                low=("low","min"), close=("close","last"),
                volume=("volume","sum"),
            ).dropna(subset=["open"]).reset_index()

            n_m15 = await _insert_bars(conn, "ohlc_m15", pair, df)  # 1h as proxy (yf no M15)
            n_h4  = await _insert_bars(conn, "ohlc_h4",  pair, df_h4)
            print(f"    → H4: {n_h4} bars | M15(1h proxy): {n_m15} bars")

        except Exception as e:
            print(f"    ERROR: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    conn = await asyncpg.connect(os.getenv("DATABASE_URL", ""))

    print("=" * 60)
    print("  Step 1: Download M5 (Dukascopy, 1 year)")
    print("=" * 60)
    await download_m5(conn)

    print()
    print("=" * 60)
    print("  Step 2: Gap-fill H4 + M15 (yfinance, last 10 days)")
    print("=" * 60)
    await refresh_h4_m15(conn)

    print()
    print("=" * 60)
    print("  Final DB state:")
    for tbl in ["ohlc_m5", "ohlc_m15", "ohlc_h4"]:
        rows = await conn.fetch(
            f"SELECT symbol, COUNT(*) as n, MAX(time)::date as latest FROM {tbl} GROUP BY symbol ORDER BY symbol"
        )
        print(f"  {tbl}:")
        for r in rows:
            print(f"    {r['symbol']:<10} {r['n']:>8} bars   latest: {r['latest']}")
    print("=" * 60)

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
