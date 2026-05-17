#!/usr/bin/env python3
"""
Download 6 years of historical OHLC data from Dukascopy's public datafeed API.

Pairs     : EURUSD, GBPUSD, USDJPY, AUDUSD, XAUUSD
Timeframes: M15, H4, W1
Output    : data/historical_csvs/{PAIR}_{TF}.csv  (MT5-compatible format)

Run:
    source venv/bin/activate
    python3 scripts/download_dukascopy.py
"""

from __future__ import annotations

import io
import lzma
import os
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

# ── Config ─────────────────────────────────────────────────────────────────────

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"]
TIMEFRAMES = ["M15", "M30", "H1", "H4", "W1"]

TODAY      = date.today()
START_DATE = date(TODAY.year - 6, TODAY.month, TODAY.day)
END_DATE   = TODAY - timedelta(days=1)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "historical_csvs"

BASE_URL    = "https://datafeed.dukascopy.com/datafeed"
MAX_WORKERS = 12
RETRY_COUNT = 3
RETRY_DELAY = 2.0

# Dukascopy bi5 1-minute candle record: big-endian, 24 bytes total
# Fields: seconds_from_day_start (uint32), open/high/low/close (uint32 each,
#         divide by PRICE_DIVISOR), volume (float32 — stored as IEEE 754)
STRUCT_FMT  = ">IIIIIf"
RECORD_SIZE = struct.calcsize(STRUCT_FMT)   # 24 bytes

# Price divisors per pair (Dukascopy stores prices as fixed-point integers)
PRICE_DIVISOR: dict[str, float] = {
    "EURUSD": 100_000.0,   # 5 decimal places
    "GBPUSD": 100_000.0,
    "AUDUSD": 100_000.0,
    "USDJPY":   1_000.0,   # 3 decimal places
    "XAUUSD":   1_000.0,   # gold in USD, 3dp
}

_HR  = "═" * 66
_HR2 = "┄" * 66


# ── Download helpers ───────────────────────────────────────────────────────────

def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
    )
    return s


def download_day(pair: str, d: date, session: requests.Session) -> Optional[bytes]:
    """
    Download and LZMA-decompress one day's 1-minute bid candle bi5 file.
    Returns None for weekends / holidays / empty days.
    """
    year  = d.year
    month = d.month - 1   # Dukascopy months are 0-indexed
    day   = d.day
    url   = f"{BASE_URL}/{pair}/{year}/{month:02d}/{day:02d}/BID_candles_min_1.bi5"

    for attempt in range(RETRY_COUNT):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 404:
                return None          # weekend or no data for this day
            r.raise_for_status()
            if len(r.content) < RECORD_SIZE:
                return None          # empty file
            return lzma.decompress(r.content)
        except lzma.LZMAError:
            return None              # corrupted / empty
        except requests.RequestException:
            if attempt < RETRY_COUNT - 1:
                time.sleep(RETRY_DELAY)
    return None


def parse_day(raw: bytes, d: date, divisor: float) -> list[dict]:
    """Parse decompressed bi5 bytes → list of 1-minute OHLCV dicts."""
    records = []
    n = len(raw) // RECORD_SIZE
    day_start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    for i in range(n):
        chunk = raw[i * RECORD_SIZE : (i + 1) * RECORD_SIZE]
        sec, open_, high, low, close, volume = struct.unpack(STRUCT_FMT, chunk)
        # Skip empty bars (price == 0)
        if open_ == 0:
            continue
        records.append({
            "time":   day_start + timedelta(seconds=int(sec)),
            "open":   open_  / divisor,
            "high":   high   / divisor,
            "low":    low    / divisor,
            "close":  close  / divisor,
            "volume": max(0, int(volume)),  # float32 → int tick count
        })
    return records


def _download_pair(pair: str) -> pd.DataFrame:
    """Download all M1 data for one pair over the 6-year window."""
    session  = _make_session()
    divisor  = PRICE_DIVISOR[pair]

    # Build list of all calendar days in range
    days = []
    d = START_DATE
    while d <= END_DATE:
        if d.weekday() < 5:    # skip Saturdays (5) and Sundays (6)
            days.append(d)
        d += timedelta(days=1)

    total   = len(days)
    done    = 0
    fetched = 0

    def _fetch(day: date) -> tuple[date, Optional[bytes]]:
        return day, download_day(pair, day, session)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_fetch, day): day for day in days}
        day_results: dict[date, list[dict]] = {}

        for fut in as_completed(futures):
            day, raw = fut.result()
            done += 1
            if raw:
                recs = parse_day(raw, day, divisor)
                if recs:
                    day_results[day] = recs
                    fetched += len(recs)

            if done % 200 == 0 or done == total:
                pct = done / total * 100
                print(f"    {pair}  {done}/{total} days ({pct:.0f}%)  "
                      f"{fetched:,} M1 bars so far", flush=True)

    # Assemble in chronological order
    all_records: list[dict] = []
    for day in sorted(day_results):
        all_records.extend(day_results[day])

    if not all_records:
        return pd.DataFrame()

    df = pd.DataFrame(all_records)
    df.sort_values("time", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ── Resampling ─────────────────────────────────────────────────────────────────

_RESAMPLE_RULES = {
    "M15": "15min",
    "M30": "30min",
    "H1":  "1h",
    "H4":  "4h",
    "W1":  "W-MON",
}


def resample(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    rule = _RESAMPLE_RULES[tf]
    df2  = df.set_index("time")
    res  = df2.resample(rule, label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna(subset=["open"])
    res = res.reset_index().rename(columns={"time": "datetime"})
    return res


# ── CSV output ─────────────────────────────────────────────────────────────────

def save_csv(df: pd.DataFrame, pair: str, tf: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{pair}_{tf}.csv"

    out = df.copy()
    out["<date>"]    = out["datetime"].dt.strftime("%Y.%m.%d")
    out["<time>"]    = out["datetime"].dt.strftime("%H:%M")
    out["<open>"]    = out["open"].round(6)
    out["<high>"]    = out["high"].round(6)
    out["<low>"]     = out["low"].round(6)
    out["<close>"]   = out["close"].round(6)
    out["<tickvol>"] = out["volume"].astype(int)
    out["<spread>"]  = 0

    cols = ["<date>", "<time>", "<open>", "<high>", "<low>", "<close>", "<tickvol>", "<spread>"]
    out[cols].to_csv(path, index=False)
    return path


# ── Price sanity check ─────────────────────────────────────────────────────────

_PRICE_RANGES = {
    "EURUSD": (0.80, 1.60),
    "GBPUSD": (1.00, 2.00),
    "USDJPY": (80.0, 165.0),
    "AUDUSD": (0.50, 1.10),
    "XAUUSD": (1000.0, 3500.0),
}


def sanity_check(df: pd.DataFrame, pair: str) -> bool:
    lo, hi = _PRICE_RANGES.get(pair, (0, 999999))
    sample_close = df["close"].median()
    if not (lo <= sample_close <= hi):
        print(f"  !! SANITY FAIL: {pair} median close={sample_close:.5f} "
              f"expected {lo}–{hi}")
        return False
    return True


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print(_HR)
    print("  Dukascopy Historical Data Downloader")
    print(f"  Pairs     : {', '.join(PAIRS)}")
    print(f"  Timeframes: {', '.join(TIMEFRAMES)}")
    print(f"  Range     : {START_DATE}  →  {END_DATE}  (~6 years)")
    print(f"  Output    : {OUTPUT_DIR}")
    print(_HR)
    print()

    summary: list[str] = []
    t0_total = time.perf_counter()

    for pair in PAIRS:
        print(_HR2)
        print(f"  Downloading {pair} M1 data ...")
        print(_HR2)
        t0 = time.perf_counter()

        df_m1 = _download_pair(pair)

        if df_m1.empty:
            print(f"  ✗  {pair}: no data retrieved")
            summary.append(f"  ✗  {pair}: no data")
            continue

        # Sanity check prices
        if not sanity_check(df_m1, pair):
            print(f"  ✗  {pair}: price sanity check failed — skipping")
            summary.append(f"  ✗  {pair}: sanity fail")
            continue

        print(f"  M1 bars total: {len(df_m1):,}  "
              f"({df_m1['time'].iloc[0].date()} → {df_m1['time'].iloc[-1].date()})")
        print()

        for tf in TIMEFRAMES:
            df_tf = resample(df_m1, tf)
            path  = save_csv(df_tf, pair, tf)
            elapsed = time.perf_counter() - t0
            print(f"  ✓  {pair} {tf:<4}  {len(df_tf):>6,} bars  → {path.name}")
            summary.append(f"  ✓  {pair} {tf}: {len(df_tf):,} bars → {path.name}")

        elapsed = time.perf_counter() - t0
        print(f"  Elapsed: {elapsed:.1f}s")
        print()

    total_elapsed = time.perf_counter() - t0_total
    print(_HR)
    print("  SUMMARY")
    print(_HR)
    for line in summary:
        print(line)
    print()
    print(f"  Total elapsed: {total_elapsed/60:.1f} min")
    print(_HR)


if __name__ == "__main__":
    main()
