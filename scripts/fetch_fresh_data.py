"""
scripts/fetch_fresh_data.py — Fill ohlc_h4 gap using Yahoo Finance.
Run from project root: python3 scripts/fetch_fresh_data.py
"""
import asyncio
from datetime import datetime, timezone
import yfinance as yf
import asyncpg
from dotenv import load_dotenv
import os

load_dotenv()

# yfinance symbol → our DB symbol
SYMBOLS = {
    "EURUSD=X": "EURUSD",
    "GBPUSD=X": "GBPUSD",
    "USDJPY=X": "USDJPY",
    "AUDUSD=X": "AUDUSD",
    "GC=F":     "XAUUSD",  # Gold futures
}

async def main():
    db = await asyncpg.connect(os.getenv("DATABASE_URL"))

    total_inserted = 0
    for yf_sym, db_sym in SYMBOLS.items():
        print(f"Fetching {db_sym} ({yf_sym})...")
        try:
            ticker = yf.Ticker(yf_sym)
            # 1y period gives plenty of history, interval=1h → we group to H4 below
            df = ticker.history(period="60d", interval="1h", auto_adjust=True)

            if df.empty:
                print(f"  No data returned for {yf_sym}")
                continue

            df = df.reset_index()
            df.rename(columns={"Datetime": "time", "Open": "open", "High": "high",
                                "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
            df["time"] = df["time"].dt.tz_convert("UTC")

            # Resample 1h → 4h to create H4 candles
            df = df.set_index("time")
            h4 = df.resample("4h").agg({
                "open":   "first",
                "high":   "max",
                "low":    "min",
                "close":  "last",
                "volume": "sum",
            }).dropna()
            h4 = h4.reset_index()

            rows = [
                (row["time"].to_pydatetime(), db_sym,
                 float(row["open"]), float(row["high"]),
                 float(row["low"]),  float(row["close"]),
                 int(row["volume"]))
                for _, row in h4.iterrows()
            ]

            inserted = await db.executemany(
                """INSERT INTO ohlc_h4 (time, symbol, open, high, low, close, volume)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   ON CONFLICT (time, symbol) DO NOTHING""",
                rows,
            )
            print(f"  {db_sym}: {len(rows)} candles fetched, inserted (skipped existing)")
            total_inserted += len(rows)

        except Exception as e:
            print(f"  ERROR {db_sym}: {e}")

    await db.close()
    print(f"\nDone. {total_inserted} candles processed total.")

if __name__ == "__main__":
    asyncio.run(main())
