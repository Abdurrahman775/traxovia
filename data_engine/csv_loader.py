"""
data_engine/csv_loader.py — Bulk historical CSV loader.

Drop MT5-exported CSV files into data/historical_csvs/ named:
    EURUSD_M15.csv   GBPUSD_H4.csv   XAUUSD_M30.csv  ...

Supported timeframes : M15  M30  H1  H4  W1
Supported pairs      : EURUSD  GBPUSD  USDJPY  AUDUSD  XAUUSD

Handles all common MT5 export column layouts automatically.
Safe to re-run — ON CONFLICT (time, symbol) DO NOTHING.

Run:
    python -m data_engine.csv_loader
    python -m data_engine.csv_loader --dir /my/custom/path
    python -m data_engine.csv_loader --file EURUSD_M15.csv
    python -m data_engine.csv_loader --retrain          # trigger model retrain after load
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()

# ── Constants ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV_DIR = PROJECT_ROOT / "data" / "historical_csvs"

VALID_PAIRS = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"}

TABLE_MAP: dict[str, str] = {
    "M15": "ohlc_m15",
    "M30": "ohlc_m30",
    "H1":  "ohlc_h1",
    "H4":  "ohlc_h4",
    "W1":  "ohlc_w1",
}

HAS_SPREAD: dict[str, bool] = {
    "M15": True,
    "M30": True,
    "H1":  True,
    "H4":  True,
    "W1":  False,
}

INSERT_CHUNK = 2_000

_HR  = "═" * 64
_HR2 = "┄" * 64

# ── MT5 CSV column normalization ───────────────────────────────────────────────
# MT5 exports in several formats; we map all known headers to canonical names.

_COL_ALIASES: dict[str, str] = {
    # Date/time columns
    "<date>":       "date",
    "date":         "date",
    "<time>":       "time_col",
    "time":         "time_col",
    "datetime":     "datetime",
    "timestamp":    "datetime",

    # OHLCV
    "<open>":       "open",
    "open":         "open",
    "<high>":       "high",
    "high":         "high",
    "<low>":        "low",
    "low":          "low",
    "<close>":      "close",
    "close":        "close",
    "<tickvol>":    "volume",
    "<vol>":        "volume",
    "tickvol":      "volume",
    "volume":       "volume",
    "vol":          "volume",
    "<spread>":     "spread",
    "spread":       "spread",
}


def _normalize_headers(raw_headers: list[str]) -> dict[str, int]:
    """Return {canonical_name: column_index} from raw CSV headers."""
    result: dict[str, int] = {}
    for i, h in enumerate(raw_headers):
        key = h.strip().lower()
        canonical = _COL_ALIASES.get(key)
        if canonical and canonical not in result:
            result[canonical] = i
    return result


# ── Filename parsing ──────────────────────────────────────────────────────────

def _parse_filename(path: Path) -> tuple[str, str] | None:
    """
    Extract (PAIR, TIMEFRAME) from filenames like:
        EURUSD_M15.csv    GBPUSD_H4.csv    eurusd_m30.csv
        EURUSD_M15_5yr.csv   XAUUSD-H1.csv
    Returns None if unrecognised.
    """
    stem = path.stem.upper()
    pattern = re.compile(
        r"(?P<pair>EURUSD|GBPUSD|USDJPY|AUDUSD|XAUUSD)"
        r"[_\-\s]+"
        r"(?P<tf>M15|M30|H1|H4|W1)"
    )
    m = pattern.search(stem)
    if not m:
        return None
    return m.group("pair"), m.group("tf")


# ── Timestamp parsing ─────────────────────────────────────────────────────────

_DT_FORMATS = [
    "%Y.%m.%d %H:%M",      # MT5 default: 2020.01.02 00:00
    "%Y.%m.%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
]


def _parse_dt(date_str: str, time_str: str = "") -> datetime | None:
    combined = (date_str.strip() + " " + time_str.strip()).strip()
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(combined, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _row_to_record(
    row: list[str],
    col_idx: dict[str, int],
    has_spread: bool,
    symbol: str,
) -> tuple | None:
    """Convert a raw CSV row to a DB record tuple. Returns None on bad rows."""
    try:
        # ── timestamp ──────────────────────────────────────────────────────────
        if "datetime" in col_idx:
            dt = _parse_dt(row[col_idx["datetime"]])
        elif "date" in col_idx and "time_col" in col_idx:
            dt = _parse_dt(row[col_idx["date"]], row[col_idx["time_col"]])
        elif "date" in col_idx:
            dt = _parse_dt(row[col_idx["date"]])
        else:
            return None

        if dt is None:
            return None

        open_  = float(row[col_idx["open"]])
        high   = float(row[col_idx["high"]])
        low    = float(row[col_idx["low"]])
        close  = float(row[col_idx["close"]])
        volume = int(float(row[col_idx.get("volume", -1)])) if "volume" in col_idx else 0

        if has_spread and "spread" in col_idx:
            spread = float(row[col_idx["spread"]])
            return (dt, symbol, open_, high, low, close, volume, spread)
        else:
            return (dt, symbol, open_, high, low, close, volume)

    except (ValueError, IndexError, KeyError):
        return None


# ── DB upsert ─────────────────────────────────────────────────────────────────

async def _upsert(
    conn: asyncpg.Connection,
    table: str,
    records: list[tuple],
    has_spread: bool,
) -> int:
    if not records:
        return 0

    if has_spread:
        sql = f"""
            INSERT INTO {table} (time, symbol, open, high, low, close, volume, spread)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (time, symbol) DO NOTHING
        """
    else:
        sql = f"""
            INSERT INTO {table} (time, symbol, open, high, low, close, volume)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (time, symbol) DO NOTHING
        """

    inserted = 0
    for i in range(0, len(records), INSERT_CHUNK):
        chunk = records[i : i + INSERT_CHUNK]
        await conn.executemany(sql, chunk)
        inserted += len(chunk)
    return inserted


# ── Single-file loader ─────────────────────────────────────────────────────────

async def load_file(
    conn: asyncpg.Connection,
    path: Path,
    pair: str | None = None,
    timeframe: str | None = None,
) -> dict:
    """
    Load one CSV file into the appropriate hypertable.
    pair/timeframe override filename detection when supplied.
    Returns a result dict with keys: ok, pair, tf, rows_read, rows_inserted, error.
    """
    # ── detect pair + timeframe ────────────────────────────────────────────────
    if not pair or not timeframe:
        parsed = _parse_filename(path)
        if not parsed:
            return {"ok": False, "pair": pair, "tf": timeframe,
                    "rows_read": 0, "rows_inserted": 0,
                    "error": "Cannot detect pair/timeframe from filename"}
        pair, timeframe = parsed

    pair      = pair.upper()
    timeframe = timeframe.upper()

    if pair not in VALID_PAIRS:
        return {"ok": False, "pair": pair, "tf": timeframe,
                "rows_read": 0, "rows_inserted": 0,
                "error": f"Unknown pair '{pair}'"}

    if timeframe not in TABLE_MAP:
        return {"ok": False, "pair": pair, "tf": timeframe,
                "rows_read": 0, "rows_inserted": 0,
                "error": f"Unknown timeframe '{timeframe}'"}

    table      = TABLE_MAP[timeframe]
    has_spread = HAS_SPREAD[timeframe]

    # ── parse CSV ──────────────────────────────────────────────────────────────
    records:    list[tuple] = []
    bad_rows:   int         = 0

    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader  = csv.reader(f)
            headers = next(reader)
            col_idx = _normalize_headers(headers)

            if "open" not in col_idx or "close" not in col_idx:
                return {"ok": False, "pair": pair, "tf": timeframe,
                        "rows_read": 0, "rows_inserted": 0,
                        "error": f"Required columns not found. Headers seen: {headers[:8]}"}

            for row in reader:
                if not any(row):
                    continue
                rec = _row_to_record(row, col_idx, has_spread, pair)
                if rec:
                    records.append(rec)
                else:
                    bad_rows += 1

    except Exception as exc:
        return {"ok": False, "pair": pair, "tf": timeframe,
                "rows_read": 0, "rows_inserted": 0, "error": str(exc)}

    rows_read = len(records)

    # ── insert ────────────────────────────────────────────────────────────────
    try:
        inserted = await _upsert(conn, table, records, has_spread)
    except Exception as exc:
        return {"ok": False, "pair": pair, "tf": timeframe,
                "rows_read": rows_read, "rows_inserted": 0, "error": str(exc)}

    return {
        "ok":            True,
        "pair":          pair,
        "tf":            timeframe,
        "rows_read":     rows_read,
        "rows_inserted": inserted,
        "bad_rows":      bad_rows,
        "error":         None,
    }


# ── Progress printer ───────────────────────────────────────────────────────────

def _print_result(r: dict) -> None:
    mark = "✓" if r["ok"] else "✗"
    if r["ok"]:
        already = r["rows_read"] - r["rows_inserted"]
        note    = f"  ({already:,} already in DB)" if already > 0 else ""
        bad     = f"  [{r['bad_rows']} skipped]" if r.get("bad_rows") else ""
        print(
            f"  {mark}  {r['pair']:<8} {r['tf']:<4}  "
            f"read {r['rows_read']:>7,}   inserted {r['rows_inserted']:>7,}"
            f"{note}{bad}"
        )
    else:
        print(f"  {mark}  {r['pair'] or '?':<8} {r['tf'] or '?':<4}  ERROR: {r['error']}")


# ── Main ───────────────────────────────────────────────────────────────────────

async def main(args: argparse.Namespace) -> None:
    t0      = time.perf_counter()
    db_url  = os.getenv("DATABASE_URL", "")

    if not db_url:
        print("ERROR: DATABASE_URL not set in .env", file=sys.stderr)
        sys.exit(1)

    # ── resolve files ──────────────────────────────────────────────────────────
    if args.file:
        target = Path(args.file)
        if not target.is_absolute():
            target = Path(args.dir) / target
        if not target.exists():
            print(f"ERROR: File not found: {target}", file=sys.stderr)
            sys.exit(1)
        files = [target]
    else:
        csv_dir = Path(args.dir)
        if not csv_dir.exists():
            csv_dir.mkdir(parents=True)
            print(f"Created directory: {csv_dir}")
            print("Drop your CSV files there and re-run.")
            sys.exit(0)
        files = sorted(csv_dir.glob("*.csv"))
        if not files:
            print(f"No CSV files found in {csv_dir}")
            print("Expected names like: EURUSD_M15.csv  GBPUSD_H4.csv")
            sys.exit(0)

    # ── header ────────────────────────────────────────────────────────────────
    print(_HR)
    print("  Traxovia AI — Historical CSV Loader")
    print(f"  DB  : {db_url.split('@')[-1]}")
    print(f"  Files: {len(files)}")
    print(_HR)

    conn    = await asyncpg.connect(db_url)
    results = []

    try:
        for path in files:
            print(f"\n  Loading {path.name} ...")
            result = await load_file(conn, path, args.pair or None, args.timeframe or None)
            _print_result(result)
            results.append(result)
    finally:
        await conn.close()

    # ── summary ────────────────────────────────────────────────────────────────
    elapsed     = time.perf_counter() - t0
    total_read  = sum(r["rows_read"]     for r in results)
    total_ins   = sum(r["rows_inserted"] for r in results)
    succeeded   = sum(1 for r in results if r["ok"])

    print()
    print(_HR)
    print(f"  {'✓' if succeeded == len(results) else '✗'}  {succeeded}/{len(results)} files OK")
    print(f"  Rows read     : {total_read:,}")
    print(f"  Rows inserted : {total_ins:,}")
    print(f"  Elapsed       : {elapsed:.1f}s")
    print(_HR)

    # ── optional retrain ───────────────────────────────────────────────────────
    if args.retrain and total_ins > 0:
        print("\n  Triggering model retrain ...")
        try:
            from scheduler.tasks import retrain_model
            retrain_model.delay()
            print("  ✓  Retrain task queued in Celery")
        except Exception as exc:
            print(f"  ✗  Could not queue retrain: {exc}")

    if succeeded < len(results):
        sys.exit(1)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Load historical OHLC CSV files into TimescaleDB")
    p.add_argument("--dir",       default=str(DEFAULT_CSV_DIR),
                   help="Directory containing CSV files (default: data/historical_csvs/)")
    p.add_argument("--file",      default="",
                   help="Load a single file instead of the whole directory")
    p.add_argument("--pair",      default="",
                   help="Override pair detection (e.g. EURUSD)")
    p.add_argument("--timeframe", default="",
                   help="Override timeframe detection (e.g. M15)")
    p.add_argument("--retrain",   action="store_true",
                   help="Queue model retrain after successful load")
    return p


if __name__ == "__main__":
    asyncio.run(main(_build_parser().parse_args()))
