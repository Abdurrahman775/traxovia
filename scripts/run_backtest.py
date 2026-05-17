#!/usr/bin/env python3
"""
scripts/run_backtest.py — Load historical data from DB and run walk-forward backtest.

Fetches H4 (regime/bias) and M15 (entry) OHLC data from TimescaleDB for each pair,
wraps the BOS strategy into the BacktestEngine callback format, runs walk-forward
validation, and prints a results table.

Run:
    source venv/bin/activate
    python3 scripts/run_backtest.py
    python3 scripts/run_backtest.py --pair EURUSD
    python3 scripts/run_backtest.py --pair EURUSD --timeframe M15
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import asyncpg
import pandas as pd
from dotenv import load_dotenv

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.engine import BacktestEngine, Signal
from core.ai_engine.walk_forward import WalkForwardValidator
from core.structure_engine.bos_identifier import BOSIdentifier
from core.structure_engine.regime_classifier import RegimeClassifier

load_dotenv()

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"]

PIP_SIZE: dict[str, float] = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "AUDUSD": 0.0001,
    "USDJPY": 0.01,
    "XAUUSD": 0.10,
}

_HR  = "═" * 70
_HR2 = "┄" * 70


# ── DB helpers ─────────────────────────────────────────────────────────────────

async def fetch_ohlc(
    conn: asyncpg.Connection,
    table: str,
    symbol: str,
    limit: int = 0,
) -> pd.DataFrame:
    sql = f"""
        SELECT time, open, high, low, close, volume
        FROM   {table}
        WHERE  symbol = $1
        ORDER  BY time ASC
        {"LIMIT " + str(limit) if limit else ""}
    """
    rows = await conn.fetch(sql, symbol)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].astype(float)
    df["volume"] = df["volume"].astype(int)
    df.sort_values("time", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ── Strategy wrapper ───────────────────────────────────────────────────────────

def make_bos_strategy(pip_size: float):
    """
    Return a strategy callable for BacktestEngine.run().

    Uses the last 50 bars for regime classification (H4-proxy on M15 data)
    and BOSIdentifier for entry signals. SL = 20 pips, TP = 40 pips (2R).
    """
    regime_clf = RegimeClassifier()
    bos_id     = BOSIdentifier(n=3)
    SL_PIPS    = 20.0
    TP_PIPS    = 40.0

    def strategy(df: pd.DataFrame) -> Optional[Signal]:
        if len(df) < 55:
            return None

        window = df.iloc[-50:].reset_index(drop=True)

        # Gate 1 — Regime must not be blocked
        regime = regime_clf.classify(window)
        if regime["signal_gate"] == "blocked":
            return None

        # Gate 2 — BOS on last bar
        bos_df  = bos_id.identify(window)
        last    = bos_df.iloc[-1]
        bullish = bool(last.get("bullish_bos", False))
        bearish = bool(last.get("bearish_bos", False))

        if not bullish and not bearish:
            return None

        direction   = "buy" if bullish else "sell"
        entry_price = float(df["close"].iloc[-1])

        return Signal(
            direction=direction,
            sl_pips=SL_PIPS,
            tp_pips=TP_PIPS,
            entry_price=entry_price,
        )

    return strategy


# ── Backtest runner ────────────────────────────────────────────────────────────

async def run_pair(
    conn: asyncpg.Connection,
    pair: str,
    timeframe: str,
) -> dict:
    table_map = {
        "M15": "ohlc_m15", "M30": "ohlc_m30",
        "H1":  "ohlc_h1",  "H4":  "ohlc_h4",
    }
    table = table_map.get(timeframe)
    if not table:
        return {"pair": pair, "tf": timeframe, "ok": False,
                "error": f"Unsupported timeframe {timeframe}"}

    df = await fetch_ohlc(conn, table, pair)
    if df.empty:
        return {"pair": pair, "tf": timeframe, "ok": False,
                "error": "No data in DB"}

    pip     = PIP_SIZE.get(pair, 0.0001)
    strat   = make_bos_strategy(pip)
    wfv     = WalkForwardValidator(pip_size=pip)

    try:
        result = wfv.run(df, strat)
    except ValueError as e:
        return {"pair": pair, "tf": timeframe, "ok": False, "error": str(e)}

    return {
        "pair":       pair,
        "tf":         timeframe,
        "ok":         True,
        "bars":       len(df),
        "windows":    result.n_windows,
        "avg_sharpe": result.avg_sharpe,
        "avg_wr":     result.avg_win_rate,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

async def main(args: argparse.Namespace) -> None:
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set in .env", file=sys.stderr)
        sys.exit(1)

    pairs      = [args.pair.upper()] if args.pair else PAIRS
    timeframes = [args.timeframe.upper()] if args.timeframe else ["M15", "H4"]

    print(_HR)
    print("  Traxovia AI — Walk-Forward Backtest")
    print(f"  Pairs     : {', '.join(pairs)}")
    print(f"  Timeframes: {', '.join(timeframes)}")
    print(f"  DB        : {db_url.split('@')[-1]}")
    print(_HR)

    conn    = await asyncpg.connect(db_url)
    results = []

    try:
        for pair in pairs:
            for tf in timeframes:
                print(f"  Running {pair} {tf} ...", flush=True)
                r = await run_pair(conn, pair, tf)
                results.append(r)
                if r["ok"]:
                    print(f"    bars={r['bars']:,}  windows={r['windows']}  "
                          f"avg_sharpe={r['avg_sharpe']:.4f}  avg_wr={r['avg_wr']:.1f}%")
                else:
                    print(f"    ✗  {r['error']}")
    finally:
        await conn.close()

    # ── Summary table ──────────────────────────────────────────────────────────
    print()
    print(_HR)
    print(f"  {'Pair':<8} {'TF':<5} {'Bars':>8} {'Windows':>8} {'Avg Sharpe':>12} {'Avg WR%':>9}  Status")
    print(_HR2)
    for r in results:
        if r["ok"]:
            print(f"  {r['pair']:<8} {r['tf']:<5} {r['bars']:>8,} {r['windows']:>8} "
                  f"{r['avg_sharpe']:>12.4f} {r['avg_wr']:>8.1f}%  ✓")
        else:
            print(f"  {r['pair']:<8} {r['tf']:<5} {'—':>8} {'—':>8} {'—':>12} {'—':>9}  ✗ {r['error']}")
    print(_HR)

    ok = sum(1 for r in results if r["ok"])
    print(f"  {ok}/{len(results)} pairs ran successfully")
    print(_HR)

    if ok < len(results):
        sys.exit(1)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Walk-forward backtest using DB data")
    p.add_argument("--pair",      default="", help="Single pair, e.g. EURUSD (default: all)")
    p.add_argument("--timeframe", default="", help="Single timeframe, e.g. M15 (default: M15 + H4)")
    return p


if __name__ == "__main__":
    asyncio.run(main(_parser().parse_args()))
