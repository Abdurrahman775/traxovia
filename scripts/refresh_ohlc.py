"""
scripts/refresh_ohlc.py — Gap-fill ohlc_m15 and ohlc_h4 for all 5 pairs via yfinance.

Uses 15-minute interval data (max 60-day history from yfinance) and aggregates
to H4 for the H4 table. Safe to run repeatedly — ON CONFLICT DO NOTHING.

Called automatically by paper_trading_loop.py at startup and every 4 hours,
and can be run manually:

    source venv/bin/activate
    python3 scripts/refresh_ohlc.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import asyncpg
import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

# yfinance symbol → DB symbol
YF_MAP: dict[str, str] = {
    "EURUSD=X": "EURUSD",
    "GBPUSD=X": "GBPUSD",
    "USDJPY=X": "USDJPY",
    "AUDUSD=X": "AUDUSD",
    "GC=F":     "XAUUSD",
}

_HR = "─" * 60


async def _upsert_bars(conn: asyncpg.Connection, table: str, symbol: str,
                       df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rows = [
        (row["time"], symbol,
         float(row["open"]), float(row["high"]),
         float(row["low"]),  float(row["close"]),
         int(row["volume"]))
        for _, row in df.iterrows()
        if not (pd.isna(row["open"]) or pd.isna(row["close"]))
    ]
    if not rows:
        return 0
    await conn.executemany(
        f"""INSERT INTO {table} (time, symbol, open, high, low, close, volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (time, symbol) DO NOTHING""",
        rows,
    )
    return len(rows)


def _to_h4(df_15m: pd.DataFrame) -> pd.DataFrame:
    """Resample 15-minute bars to H4 OHLCV."""
    df = df_15m.set_index("time").sort_index()
    h4 = df.resample("4h", label="left", closed="left").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna(subset=["open", "close"]).reset_index()
    h4 = h4[h4["close"].notna() & h4["open"].notna()]
    return h4


async def refresh(conn: asyncpg.Connection, days: int = 55) -> dict:
    """Download last `days` days of 15m data and upsert M15 + H4 for all pairs."""
    try:
        import yfinance as yf
    except ImportError:
        print("  yfinance not installed — run: pip install yfinance")
        return {}

    results: dict[str, dict] = {}

    for yf_sym, db_sym in YF_MAP.items():
        print(f"  {db_sym:<8} fetching {days}d 15m from yfinance ...", end="", flush=True)
        try:
            ticker = yf.Ticker(yf_sym)
            raw    = ticker.history(period=f"{days}d", interval="15m", auto_adjust=True)

            if raw.empty:
                print(f"  no data")
                results[db_sym] = {"m15": 0, "h4": 0}
                continue

            raw = raw.reset_index()

            # Normalise column names
            raw.columns = [c.lower() for c in raw.columns]
            time_col = next((c for c in raw.columns if "datetime" in c or c == "date"), None)
            if time_col:
                raw.rename(columns={time_col: "time"}, inplace=True)

            # Ensure UTC-aware timestamps
            if raw["time"].dt.tz is None:
                raw["time"] = raw["time"].dt.tz_localize("UTC")
            else:
                raw["time"] = raw["time"].dt.tz_convert("UTC")

            # Floor to 15-minute boundary and deduplicate
            raw["time"] = raw["time"].dt.floor("15min")
            raw = raw.drop_duplicates(subset=["time"]).sort_values("time")

            df_m15 = raw[["time", "open", "high", "low", "close", "volume"]].copy()
            df_h4  = _to_h4(df_m15)

            n_m15 = await _upsert_bars(conn, "ohlc_m15", db_sym, df_m15)
            n_h4  = await _upsert_bars(conn, "ohlc_h4",  db_sym, df_h4)

            print(f"  M15 +{n_m15:>4}  H4 +{n_h4:>3}")
            results[db_sym] = {"m15": n_m15, "h4": n_h4}

        except Exception as e:
            print(f"  ERROR: {e}")
            results[db_sym] = {"m15": 0, "h4": 0, "error": str(e)}

    return results


async def main() -> None:
    db_url = os.environ["DATABASE_URL"].replace("postgresql://", "postgres://", 1)
    conn   = await asyncpg.connect(db_url)

    print(f"\n{_HR}")
    print(f"  OHLC Refresh — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Pairs: {', '.join(YF_MAP.values())}")
    print(f"{_HR}")

    results = await refresh(conn)

    total_m15 = sum(v.get("m15", 0) for v in results.values())
    total_h4  = sum(v.get("h4",  0) for v in results.values())
    print(f"{_HR}")
    print(f"  Total inserted — M15: {total_m15}  H4: {total_h4}")
    print(f"{_HR}\n")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
