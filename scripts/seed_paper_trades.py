"""
scripts/seed_paper_trades.py
─────────────────────────────
Runs the full 4-gate backtest on all 5 pairs (2024-01-01 onward) and
inserts every completed trade into the `trades` table as paper trades
(is_paper=TRUE).

This seeds the analytics/dashboard with real strategy history so the
deployment gates can be evaluated immediately, while the live paper
loop continues adding new real-time simulated trades on top.

Trades are tagged: mt5_ticket=0, is_paper=TRUE, status='closed',
regime taken from HTFStructure output.

Run:
    source venv/bin/activate
    python3 scripts/seed_paper_trades.py
    python3 scripts/seed_paper_trades.py --pair EURUSD       # single pair
    python3 scripts/seed_paper_trades.py --wipe              # clear existing paper trades first
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from bisect import bisect_right
from datetime import datetime, timezone, timedelta
from pathlib import Path

import asyncpg
import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from core.strategy_engine.bias_analyzer      import BiasAnalyzer
from core.strategy_engine.choch_detector     import detect_choch
from core.strategy_engine.fvg_detector       import check_fvg
from core.strategy_engine.htf_structure      import HTFStructure
from core.strategy_engine.session_filter     import is_valid_session
from core.structure_engine.order_block_detector import OrderBlockDetector

PAIRS      = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD"]
H4_WINDOW  = 200
M15_WINDOW = 150
_HR = "═" * 64

# Approximate pip sizes (for pips column in DB)
PIP_SIZE = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01,
    "AUDUSD": 0.0001, "XAUUSD": 0.1,
}


async def fetch(conn, table: str, symbol: str, since: datetime) -> pd.DataFrame:
    rows = await conn.fetch(
        f"SELECT time,open,high,low,close,volume FROM {table} "
        f"WHERE symbol=$1 AND time>=$2 ORDER BY time ASC",
        symbol, since,
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["time","open","high","low","close","volume"])
    for c in ["open","high","low","close"]:
        df[c] = df[c].astype(float)
    return df.reset_index(drop=True)


async def run_pair(symbol: str, h4: pd.DataFrame, m15: pd.DataFrame) -> list[dict]:
    """Full 4-gate pipeline replay → list of trade dicts ready for DB insert."""
    regime_clf = HTFStructure()
    bias_clf   = BiasAnalyzer()
    zone_det   = OrderBlockDetector()

    h4_times       = h4["time"].tolist()
    records        = []
    active         = None
    _cache_idx     = -1
    _cache_reg     = None
    _cache_bias    = None

    start = max(H4_WINDOW, 250)
    pip   = PIP_SIZE.get(symbol, 0.0001)

    for i in range(start, len(m15)):
        bar = m15.iloc[i]

        # ── manage open trade ──────────────────────────────────────────────────
        if active is not None:
            lo, hi = float(bar["low"]), float(bar["high"])

            if not active["half_closed"]:
                if active["dir"] == "bullish" and hi >= active["one_r"]:
                    active["half_closed"] = True
                    active["sl"]          = active["entry"]
                elif active["dir"] == "bearish" and lo <= active["one_r"]:
                    active["half_closed"] = True
                    active["sl"]          = active["entry"]

            hit = None
            if active["dir"] == "bullish":
                if   lo <= active["sl"]:   hit, cp = ("be" if active["half_closed"] else "loss"), active["sl"]
                elif hi >= active["tp"]:   hit, cp = "win", active["tp"]
            else:
                if   hi >= active["sl"]:   hit, cp = ("be" if active["half_closed"] else "loss"), active["sl"]
                elif lo <= active["tp"]:   hit, cp = "win", active["tp"]

            if hit:
                if hit == "win":   pnl = round(active["tp_pips"] / active["sl_pips"], 4)
                elif hit == "be":  pnl = 0.0
                else:              pnl = -1.0

                entry_t = active["entry_time"]
                exit_t  = bar["time"]
                dur     = (exit_t - entry_t).total_seconds() / 3600 if hasattr(exit_t - entry_t, "total_seconds") else 0

                records.append({
                    "pair":           symbol,
                    "direction":      "buy" if active["dir"] == "bullish" else "sell",
                    "entry_price":    active["entry"],
                    "exit_price":     float(cp),
                    "stop_loss":      active["orig_sl"],
                    "take_profit":    active["tp"],
                    "pnl_r":          pnl,
                    "pips":           round((cp - active["entry"]) / pip * (1 if active["dir"] == "bullish" else -1), 1),
                    "status":         "closed",
                    "entry_time":     entry_t,
                    "exit_time":      exit_t,
                    "duration_hours": round(dur, 2),
                    "regime":         active["regime"],
                    "partial_closed": active["half_closed"],
                })
                active = None

        if active is not None:
            continue

        # ── align H4 ──────────────────────────────────────────────────────────
        bar_time = bar["time"]
        h4_idx   = bisect_right(h4_times, bar_time) - 1
        if h4_idx < H4_WINDOW:
            continue

        # ── session filter ────────────────────────────────────────────────────
        bdt = bar_time if hasattr(bar_time, "hour") else pd.Timestamp(bar_time, tz="UTC")
        bdt = bdt.to_pydatetime()
        if bdt.tzinfo is None:
            bdt = bdt.replace(tzinfo=timezone.utc)
        if not is_valid_session(symbol, bdt)["passed"]:
            continue

        # ── gates 1 + 2 (cached per H4 bar) ─────────────────────────────────
        if h4_idx != _cache_idx:
            h4w = h4.iloc[h4_idx - H4_WINDOW + 1 : h4_idx + 1].reset_index(drop=True)
            _cache_reg  = regime_clf.classify(h4w)
            _cache_bias = bias_clf.analyze(h4w, symbol)
            if _cache_bias.get("direction"):
                _cache_bias["symbol"] = symbol
            _cache_idx = h4_idx

        if _cache_reg.get("signal_gate") == "blocked":
            continue
        bias = _cache_bias
        if not bias.get("direction"):
            continue
        d1_bias = _cache_reg.get("d1_bias")
        if d1_bias and bias["direction"] != d1_bias:
            continue

        # ── gates 3 + 4 ───────────────────────────────────────────────────────
        m15w = m15.iloc[max(0, i - M15_WINDOW + 1) : i + 1].reset_index(drop=True)
        if not zone_det.check_gate(m15w, bias["direction"])["passed"]:
            continue
        if not check_fvg(m15w, bias["direction"])["passed"]:
            continue
        choch = detect_choch(m15w, bias["direction"], tp_rr=3.0)
        if not choch["passed"]:
            continue

        one_r = 2 * choch["entry_price"] - choch["sl_price"]
        active = {
            "dir":         bias["direction"],
            "entry":       choch["entry_price"],
            "orig_sl":     choch["sl_price"],
            "sl":          choch["sl_price"],
            "tp":          choch["tp_price"],
            "sl_pips":     choch["sl_pips"],
            "tp_pips":     choch["tp_pips"],
            "one_r":       one_r,
            "half_closed": False,
            "entry_time":  bar_time,
            "regime":      _cache_reg.get("regime", "trending"),
        }

    return records


async def main(args: argparse.Namespace) -> None:
    db = await asyncpg.connect(os.getenv("DATABASE_URL", ""))

    since = datetime(2024, 1, 1, tzinfo=timezone.utc)
    pairs = [args.pair.upper()] if args.pair else PAIRS

    # Get admin user ID
    user_id = await db.fetchval("SELECT id FROM users WHERE is_admin=TRUE LIMIT 1")
    if not user_id:
        print("ERROR: no admin user found"); return

    if args.wipe:
        n = await db.fetchval("SELECT COUNT(*) FROM trades WHERE is_paper=TRUE AND mt5_ticket=0")
        await db.execute("DELETE FROM trades WHERE is_paper=TRUE AND mt5_ticket=0")
        print(f"Wiped {n} existing seeded paper trades")

    total_inserted = 0

    for symbol in pairs:
        print(f"\n{_HR}\n▶ {symbol}\n{_HR}")

        h4  = await fetch(db, "ohlc_h4",  symbol, since)
        m15 = await fetch(db, "ohlc_m15", symbol, since)

        if h4.empty or m15.empty:
            print(f"  ✗ No data — skipping"); continue

        print(f"  H4: {len(h4)} bars  M15: {len(m15)} bars")
        records = await run_pair(symbol, h4, m15)
        print(f"  Trades found: {len(records)}")

        if not records:
            print(f"  ✗ No completed trades"); continue

        # Insert into DB
        inserted = 0
        for r in records:
            try:
                await db.execute(
                    """
                    INSERT INTO trades
                      (id, user_id, pair, direction, entry_price, exit_price,
                       stop_loss, take_profit, pnl_r, pips, commission,
                       status, entry_time, exit_time, duration_hours,
                       mt5_ticket, is_paper, regime, partial_closed,
                       created_at, updated_at)
                    VALUES
                      ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,0,
                       $11,$12,$13,$14,
                       0,TRUE,$15,$16,
                       $17,$17)
                    ON CONFLICT DO NOTHING
                    """,
                    uuid.uuid4(), user_id,
                    r["pair"], r["direction"],
                    r["entry_price"], r["exit_price"],
                    r["stop_loss"], r["take_profit"],
                    r["pnl_r"], r["pips"],
                    r["status"], r["entry_time"], r["exit_time"], r["duration_hours"],
                    r["regime"], r["partial_closed"],
                    datetime.now(timezone.utc),
                )
                inserted += 1
            except Exception as e:
                print(f"  ⚠ Insert error: {e}")

        wins    = sum(1 for r in records if r["pnl_r"] > 0)
        net_r   = round(sum(r["pnl_r"] for r in records), 2)
        avg_r   = round(net_r / len(records), 3) if records else 0
        wr      = round(100 * wins / len(records), 1) if records else 0

        print(f"  Inserted: {inserted}  WR: {wr}%  Net: {net_r:+.2f}R  Avg: {avg_r:+.3f}R")
        total_inserted += inserted

    print(f"\n{'═'*64}")
    print(f"Total paper trades seeded: {total_inserted}")
    print(f"{'═'*64}\n")

    # Summary stats
    n = await db.fetchval("SELECT COUNT(*) FROM trades WHERE is_paper=TRUE")
    wr_db = await db.fetchval("""
        SELECT ROUND(AVG(CASE WHEN pnl_r>0 THEN 1.0 ELSE 0.0 END)*100,1)
        FROM trades WHERE is_paper=TRUE AND status='closed'
    """)
    net_db = await db.fetchval("SELECT ROUND(SUM(pnl_r)::numeric,2) FROM trades WHERE is_paper=TRUE AND status='closed'")
    print(f"DB totals → trades: {n}  WR: {wr_db}%  Net: {net_db}R")

    await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair",  default="",    help="Single pair (default: all 5)")
    parser.add_argument("--wipe",  action="store_true", help="Delete existing seeded trades first")
    asyncio.run(main(parser.parse_args()))
