# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Three scripts for getting OHLC candle data into TimescaleDB. All upserts use `ON CONFLICT (time, symbol) DO NOTHING` — every script is safe to re-run.

| File | Purpose | When to use |
|---|---|---|
| `historical_loader.py` | One-shot bootstrap from live MT5 | Fresh install; fills the hypertables from scratch |
| `csv_loader.py` | Bulk load from MT5-exported CSV files | Backfilling gaps, importing Dukascopy data, offline data |
| `realtime_feed.py` | Ongoing candle sync from MT5 | Called every 15 min by `update_realtime_feed` Celery task |

All three require the MetaTrader5 Python package (`historical_loader` and `realtime_feed`) or CSV files (`csv_loader`). `historical_loader` and `realtime_feed` **only run on Windows** — they call `mt5.initialize()` directly. On Linux they detect `_MT5_AVAILABLE = False` and exit cleanly.

## `historical_loader.py` — Bootstrap

Run once on a fresh Windows VPS after `init_db.py`:

```bash
python -m data_engine.historical_loader
```

### Load plan

| Timeframe | Table | Bars | Coverage |
|---|---|---|---|
| M15 | `ohlc_m15` | 8 640 | ≈ 3 months |
| H4 | `ohlc_h4` | 1 500 | ≈ 1 year |
| W1 | `ohlc_w1` | 104 | ≈ 2 years |

Pairs: EURUSD, GBPUSD, USDJPY, AUDUSD, XAUUSD.

### W1 quality gate

After loading W1 the script verifies each pair has ≥ 52 weekly bars. If the gate fails the script prints a warning and exits with code 1. The `weekly_analyzer` (Phase 3) requires ≥ 52 W1 bars to function — do not skip this gate.

Uses asyncpg (async) for DB writes; MT5 calls are wrapped in `asyncio.to_thread` to avoid blocking the event loop. Inserts in chunks of 1 000 rows.

## `csv_loader.py` — CSV Bulk Load

Drop MT5-exported CSV files into `data/historical_csvs/` named `{PAIR}_{TIMEFRAME}.csv` (e.g. `EURUSD_M15.csv`).

```bash
python -m data_engine.csv_loader                        # process all CSVs in default dir
python -m data_engine.csv_loader --dir /path/to/csvs   # custom directory
python -m data_engine.csv_loader --file EURUSD_M15.csv # single file
python -m data_engine.csv_loader --retrain              # trigger model retrain after load
```

### Supported timeframes and tables

| Timeframe | Table | Has spread column |
|---|---|---|
| M5 | `ohlc_m5` | Yes |
| M15 | `ohlc_m15` | Yes |
| M30 | `ohlc_m30` | Yes |
| H1 | `ohlc_h1` | Yes |
| H4 | `ohlc_h4` | Yes |
| W1 | `ohlc_w1` | No |

MT5 exports columns with angle-bracket names (`<date>`, `<open>`, `<tickvol>`, etc.). The loader normalises all known MT5 column aliases automatically — do not pre-process the CSV headers. Uses asyncpg for DB writes, inserts in chunks of 2 000 rows.

## `realtime_feed.py` — Ongoing Sync

Entry point: `run_realtime_update()` — called by the `update_realtime_feed` Celery task every 15 minutes.

### Per-run fetch counts

| Timeframe | Bars fetched | When |
|---|---|---|
| M15 | 3 | Every run |
| H4 | 2 | Every run |
| W1 | 2 | Mondays only (`weekday() == 0` UTC) |

### DB writes

Uses psycopg2 (`get_sync_db`) — runs inside a Celery worker, never asyncpg. Each symbol is committed individually; a failure on one symbol rolls back only that symbol's transaction and logs an error, leaving others unaffected.

`ohlc_w1` has no `spread` column — the upsert SQL omits it automatically via the `has_spread` flag.

### Silent no-op on Linux

If `MetaTrader5` is not importable, `run_realtime_update()` logs an error and returns immediately without raising. This prevents the Celery task from failing on the Linux API server — the task itself has `max_retries=3` but the function-level guard avoids pointless retries when the package is simply absent.

## Non-Negotiable Rules

- **All upserts use `ON CONFLICT (time, symbol) DO NOTHING`.** Never use `DO UPDATE` on OHLC tables — a re-run must never overwrite historical candles.
- **`historical_loader` and `realtime_feed` are Windows-only.** MT5 Python API requires a live MT5 terminal. On Linux they detect `_MT5_AVAILABLE = False` and exit/return cleanly — do not add fallback HTTP bridge code; the architecture is direct MT5.
- **`realtime_feed` uses psycopg2** (Celery context). `historical_loader` uses asyncpg (runs standalone). Never swap these.
- **W1 has no spread column.** Any upsert targeting `ohlc_w1` must use the no-spread SQL path (`has_spread=False`).
- **W1 quality gate: ≥ 52 bars per pair.** `weekly_analyzer` fails silently with bad data if this isn't met.
