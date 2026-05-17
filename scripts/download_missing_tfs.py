#!/usr/bin/env python3
"""
Download M30 and H1 data for all 5 pairs (the two timeframes missing from the first run).
Reuses the same Dukascopy datafeed logic as download_dukascopy.py.
"""

from __future__ import annotations

import lzma
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"]
TIMEFRAMES = ["M30", "H1"]   # only the missing ones

TODAY      = date.today()
START_DATE = date(TODAY.year - 6, TODAY.month, TODAY.day)
END_DATE   = TODAY - timedelta(days=1)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "historical_csvs"
BASE_URL   = "https://datafeed.dukascopy.com/datafeed"

MAX_WORKERS = 12
RETRY_COUNT = 3
RETRY_DELAY = 2.0

STRUCT_FMT  = ">IIIIIf"
RECORD_SIZE = struct.calcsize(STRUCT_FMT)

PRICE_DIVISOR: dict[str, float] = {
    "EURUSD": 100_000.0,
    "GBPUSD": 100_000.0,
    "AUDUSD": 100_000.0,
    "USDJPY":   1_000.0,
    "XAUUSD":   1_000.0,
}

_RESAMPLE_RULES = {"M30": "30min", "H1": "1h"}

_HR  = "═" * 66
_HR2 = "┄" * 66

_PRICE_RANGES = {
    "EURUSD": (0.80, 1.60),
    "GBPUSD": (1.00, 2.00),
    "USDJPY": (80.0, 165.0),
    "AUDUSD": (0.50, 1.10),
    "XAUUSD": (1000.0, 3500.0),
}


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) Firefox/124.0"
    return s


def download_day(pair: str, d: date, session: requests.Session) -> Optional[bytes]:
    year, month, day = d.year, d.month - 1, d.day
    url = f"{BASE_URL}/{pair}/{year}/{month:02d}/{day:02d}/BID_candles_min_1.bi5"
    for attempt in range(RETRY_COUNT):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 404 or len(r.content) < RECORD_SIZE:
                return None
            r.raise_for_status()
            return lzma.decompress(r.content)
        except (lzma.LZMAError, requests.RequestException):
            if attempt < RETRY_COUNT - 1:
                time.sleep(RETRY_DELAY)
    return None


def parse_day(raw: bytes, d: date, divisor: float) -> list[dict]:
    records = []
    n = len(raw) // RECORD_SIZE
    day_start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    for i in range(n):
        chunk = raw[i * RECORD_SIZE:(i + 1) * RECORD_SIZE]
        sec, o, h, l, c, v = struct.unpack(STRUCT_FMT, chunk)
        if o == 0:
            continue
        records.append({
            "time":   day_start + timedelta(seconds=int(sec)),
            "open":   o / divisor,
            "high":   h / divisor,
            "low":    l / divisor,
            "close":  c / divisor,
            "volume": max(0, int(v)),
        })
    return records


def download_pair(pair: str) -> pd.DataFrame:
    session = _make_session()
    divisor = PRICE_DIVISOR[pair]
    days = [START_DATE + timedelta(days=i)
            for i in range((END_DATE - START_DATE).days + 1)
            if (START_DATE + timedelta(days=i)).weekday() < 5]

    total, done, fetched = len(days), 0, 0
    day_results: dict[date, list[dict]] = {}

    def _fetch(d: date):
        return d, download_day(pair, d, session)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for fut in as_completed({ex.submit(_fetch, d): d for d in days}):
            d, raw = fut.result()
            done += 1
            if raw:
                recs = parse_day(raw, d, divisor)
                if recs:
                    day_results[d] = recs
                    fetched += len(recs)
            if done % 200 == 0 or done == total:
                print(f"    {pair}  {done}/{total} days ({done/total*100:.0f}%)  "
                      f"{fetched:,} M1 bars", flush=True)

    all_records: list[dict] = []
    for d in sorted(day_results):
        all_records.extend(day_results[d])

    if not all_records:
        return pd.DataFrame()
    df = pd.DataFrame(all_records)
    df.sort_values("time", inplace=True)
    return df.reset_index(drop=True)


def resample(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    res = (df.set_index("time")
             .resample(_RESAMPLE_RULES[tf], label="left", closed="left")
             .agg(open=("open","first"), high=("high","max"),
                  low=("low","min"), close=("close","last"),
                  volume=("volume","sum"))
             .dropna(subset=["open"])
             .reset_index()
             .rename(columns={"time": "datetime"}))
    return res


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
    cols = ["<date>","<time>","<open>","<high>","<low>","<close>","<tickvol>","<spread>"]
    out[cols].to_csv(path, index=False)
    return path


def main() -> None:
    print(_HR)
    print("  Dukascopy — Downloading missing timeframes: M30, H1")
    print(f"  Pairs : {', '.join(PAIRS)}")
    print(f"  Range : {START_DATE}  →  {END_DATE}")
    print(f"  Output: {OUTPUT_DIR}")
    print(_HR)

    summary: list[str] = []
    t0_total = time.perf_counter()

    for pair in PAIRS:
        print(_HR2)
        print(f"  Downloading {pair} M1 data ...")
        print(_HR2)
        t0 = time.perf_counter()

        df_m1 = download_pair(pair)
        if df_m1.empty:
            print(f"  ✗  {pair}: no data")
            summary.append(f"  ✗  {pair}: no data")
            continue

        lo, hi = _PRICE_RANGES.get(pair, (0, 999999))
        if not (lo <= df_m1["close"].median() <= hi):
            print(f"  ✗  {pair}: price sanity fail")
            summary.append(f"  ✗  {pair}: sanity fail")
            continue

        print(f"  M1 bars: {len(df_m1):,}  "
              f"({df_m1['time'].iloc[0].date()} → {df_m1['time'].iloc[-1].date()})")

        for tf in TIMEFRAMES:
            df_tf = resample(df_m1, tf)
            path  = save_csv(df_tf, pair, tf)
            print(f"  ✓  {pair} {tf:<4}  {len(df_tf):>6,} bars  → {path.name}")
            summary.append(f"  ✓  {pair} {tf}: {len(df_tf):,} bars → {path.name}")

        print(f"  Elapsed: {time.perf_counter()-t0:.1f}s\n")

    print(_HR)
    print("  SUMMARY")
    print(_HR)
    for line in summary:
        print(line)
    print(f"\n  Total elapsed: {(time.perf_counter()-t0_total)/60:.1f} min")
    print(_HR)


if __name__ == "__main__":
    main()
