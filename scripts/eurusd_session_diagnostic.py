"""
scripts/eurusd_session_diagnostic.py
─────────────────────────────────────
Per-hour WR / Net-R breakdown for any pair (no session filter applied).

Runs the full 4-gate pipeline on H4+M15 data and groups results by entry hour
so we can find the dead hours dragging Avg R down — same approach used to
tighten USDJPY and EURUSD killzones.

Usage:
    source venv/bin/activate
    python3 scripts/eurusd_session_diagnostic.py --pair EURUSD
    python3 scripts/eurusd_session_diagnostic.py --pair AUDUSD --from 2024-01-01
    python3 scripts/eurusd_session_diagnostic.py --pair GBPUSD --from 2022-01-01
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import asyncpg
import pandas as pd
from dotenv import load_dotenv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from core.strategy_engine.bias_analyzer             import BiasAnalyzer
from core.strategy_engine.choch_detector            import detect_choch
from core.strategy_engine.fvg_detector              import check_fvg
from core.strategy_engine.htf_structure             import HTFStructure
from core.structure_engine.order_block_detector     import OrderBlockDetector
from datetime import timezone as _tz

H4_WINDOW  = 200
M15_WINDOW = 150

_HR  = "═" * 72
_HR2 = "─" * 72


@dataclass
class Trade:
    hour:        int
    direction:   str
    entry_price: float
    sl_price:    float
    tp_price:    float
    sl_pips:     float
    tp_pips:     float
    one_r_price: float = 0.0
    half_closed: bool  = False
    outcome:     str   = ""
    pnl_r:       float = 0.0


async def fetch(conn, table: str, symbol: str, since: datetime | None) -> pd.DataFrame:
    sql = f"""
        SELECT time, open, high, low, close, volume
        FROM   {table}
        WHERE  symbol = $1 {"AND time >= $2" if since else ""}
        ORDER  BY time ASC
    """
    rows = await conn.fetch(sql, symbol, *([since] if since else []))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].astype(float)
    df["volume"] = df["volume"].astype(int)
    return df.reset_index(drop=True)


def run_pair_no_filter(pair: str, h4: pd.DataFrame, m15: pd.DataFrame) -> list[Trade]:
    """Run full 4-gate pipeline on any pair, NO session filter, record entry hour."""
    regime_clf = HTFStructure()
    bias_clf   = BiasAnalyzer()
    zone_det   = OrderBlockDetector()

    h4_times       = h4["time"].tolist()
    trades: list[Trade] = []
    active: Trade | None = None

    _cached_h4_idx = -1
    _cached_reg    = None
    _cached_bias   = None

    start = max(H4_WINDOW, 250)

    for i in range(start, len(m15)):
        bar = m15.iloc[i]

        # ── Close active trade ────────────────────────────────────────────
        if active is not None:
            lo = float(bar["low"])
            hi = float(bar["high"])

            if not active.half_closed:
                if active.direction == "bullish" and hi >= active.one_r_price:
                    active.half_closed = True
                    active.sl_price    = active.entry_price
                elif active.direction == "bearish" and lo <= active.one_r_price:
                    active.half_closed = True
                    active.sl_price    = active.entry_price

            hit = None
            if active.direction == "bullish":
                if lo <= active.sl_price:
                    hit, close_p = ("be_close" if active.half_closed else "loss"), active.sl_price
                elif hi >= active.tp_price:
                    hit, close_p = "win", active.tp_price
            else:
                if hi >= active.sl_price:
                    hit, close_p = ("be_close" if active.half_closed else "loss"), active.sl_price
                elif lo <= active.tp_price:
                    hit, close_p = "win", active.tp_price

            if hit:
                active.outcome = hit
                if hit == "win":
                    active.pnl_r = round(active.tp_pips / active.sl_pips, 4)
                elif hit == "be_close":
                    active.pnl_r = 0.0
                else:
                    active.pnl_r = -1.0
                trades.append(active)
                active = None

        if active is not None:
            continue

        # ── Align H4 ─────────────────────────────────────────────────────
        bar_time = bar["time"]
        h4_idx   = bisect_right(h4_times, bar_time) - 1
        if h4_idx < H4_WINDOW:
            continue

        # ── NO SESSION FILTER — record hour for diagnostics ──────────────
        bar_dt = bar_time if hasattr(bar_time, "hour") else pd.Timestamp(bar_time, tz="UTC")
        if hasattr(bar_dt, "to_pydatetime"):
            bar_dt = bar_dt.to_pydatetime()
        if bar_dt.tzinfo is None:
            bar_dt = bar_dt.replace(tzinfo=timezone.utc)
        entry_hour = bar_dt.hour

        # ── Gate 1: Regime ───────────────────────────────────────────────
        if h4_idx != _cached_h4_idx:
            h4_win       = h4.iloc[h4_idx - H4_WINDOW + 1 : h4_idx + 1].reset_index(drop=True)
            _cached_reg  = regime_clf.classify(h4_win)
            _cached_bias = bias_clf.analyze(h4_win, pair)
            if _cached_bias.get("direction"):
                _cached_bias["symbol"] = pair
            _cached_h4_idx = h4_idx

        if _cached_reg.get("signal_gate") == "blocked":
            continue

        # ── Gate 2: H4 Bias ──────────────────────────────────────────────
        bias = _cached_bias
        if not bias.get("direction"):
            continue
        d1_bias = _cached_reg.get("d1_bias")
        if d1_bias and bias["direction"] != d1_bias:
            continue

        # ── Gate 3: Order Block ──────────────────────────────────────────
        m15_win = m15.iloc[max(0, i - M15_WINDOW + 1) : i + 1].reset_index(drop=True)
        zone = zone_det.check_gate(m15_win, bias["direction"])
        if not zone["passed"]:
            continue

        # ── Gate 3b: FVG ─────────────────────────────────────────────────
        fvg = check_fvg(m15_win, bias["direction"])
        if not fvg["passed"]:
            continue

        # ── Gate 4b: CHOCH ───────────────────────────────────────────────
        choch = detect_choch(m15_win, bias["direction"], tp_rr=3.0)
        if not choch["passed"]:
            continue

        one_r = 2 * choch["entry_price"] - choch["sl_price"]

        active = Trade(
            hour        = entry_hour,
            direction   = bias["direction"],
            entry_price = choch["entry_price"],
            sl_price    = choch["sl_price"],
            tp_price    = choch["tp_price"],
            sl_pips     = choch["sl_pips"],
            tp_pips     = choch["tp_pips"],
            one_r_price = one_r,
        )

    return trades


def print_hourly_breakdown(trades: list[Trade]) -> list[tuple[int, int, float, float]]:
    """Print per-hour stats table. Returns list of (hour, trades, wr, net_r) for filtering."""
    # Group by hour
    by_hour: dict[int, list[Trade]] = defaultdict(list)
    for t in trades:
        by_hour[t.hour].append(t)

    print(f"\n{_HR}")
    print(f"  EURUSD Per-Hour Breakdown (UTC)  —  {len(trades)} total trades")
    print(f"{_HR}")
    print(f"  {'Hour':>4}  {'Trades':>6}  {'Wins':>5}  {'Losses':>6}  {'WR%':>6}  {'Net R':>7}  {'Avg R':>7}  Session")
    print(f"{_HR2}")

    rows = []
    for hour in range(24):
        ts = by_hour.get(hour, [])
        if not ts:
            continue
        n       = len(ts)
        wins    = sum(1 for t in ts if t.outcome in ("win", "be_close"))
        losses  = n - wins
        wr      = round(100 * wins / n, 1) if n else 0.0
        net_r   = round(sum(t.pnl_r for t in ts), 2)
        avg_r   = round(net_r / n, 4) if n else 0.0

        # Label the session
        if   0  <= hour < 3:   sess = "Tokyo"
        elif 3  <= hour < 8:   sess = "London Pre"
        elif 8  <= hour < 12:  sess = "London"
        elif 12 <= hour < 17:  sess = "NY"
        else:                  sess = "NY/overnight"

        flag = "✅" if wr >= 50 and avg_r >= 0.10 else ("⚠️" if wr >= 40 or avg_r >= 0.0 else "❌")
        print(f"  {hour:>4}h  {n:>6}  {wins:>5}  {losses:>6}  {wr:>5}%  {net_r:>+7.2f}  {avg_r:>+7.4f}  {sess} {flag}")
        rows.append((hour, n, wr, net_r, avg_r))

    print(f"{_HR}")
    return rows


def recommend_windows(rows: list[tuple]) -> list[tuple[int, int]]:
    """Auto-recommend session windows by keeping hours with WR≥45% or positive Net R."""
    keep_hours = []
    for hour, n, wr, net_r, avg_r in rows:
        if n < 3:
            continue  # too few samples — skip
        if wr >= 45 or (net_r > 0 and avg_r >= 0.05):
            keep_hours.append(hour)

    if not keep_hours:
        return [(7, 17)]  # fallback to default

    # Merge consecutive hours into windows
    keep_hours.sort()
    windows = []
    start = keep_hours[0]
    prev  = keep_hours[0]
    for h in keep_hours[1:]:
        if h == prev + 1:
            prev = h
        else:
            windows.append((start, prev + 1))
            start = h
            prev  = h
    windows.append((start, prev + 1))
    return windows


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default="EURUSD",
                        help="Pair to analyse e.g. AUDUSD (default: EURUSD)")
    parser.add_argument("--from", dest="since", default="",
                        help="Start date e.g. 2024-01-01 (default: all data)")
    args  = parser.parse_args()
    pair  = args.pair.upper()
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc) if args.since else None

    # Look up what the current session window is for this pair
    from core.strategy_engine.session_filter import _SESSION_MAP, _DEFAULT_SESSIONS
    cur_windows = _SESSION_MAP.get(pair, _DEFAULT_SESSIONS)

    print(f"\n{_HR}")
    print(f"  {pair} Session Diagnostic — Traxovia AI")
    print(f"  Pipeline    : Regime → HTF Bias → OB → FVG → CHOCH")
    print(f"  Filter      : NONE (all 24h, finding dead zones)")
    print(f"  Since       : {since.date() if since else 'all data'}")
    print(f"  Current win : {cur_windows}")
    print(f"{_HR}")

    db_url = os.environ["DATABASE_URL"].replace("postgresql://", "postgres://", 1)
    conn   = await asyncpg.connect(db_url)

    print(f"\n  Loading {pair} H4 + M15 data...", end="", flush=True)
    h4  = await fetch(conn, "ohlc_h4",  pair, since)
    m15 = await fetch(conn, "ohlc_m15", pair, since)
    await conn.close()
    print(f"  H4={len(h4):,} bars  M15={len(m15):,} bars")

    if h4.empty or m15.empty:
        print("  ERROR: No data found. Check DB.")
        return

    print(f"  Running pipeline (no session filter)...", end="", flush=True)
    trades = run_pair_no_filter(pair, h4, m15)
    print(f"  {len(trades)} trades found\n")

    rows = print_hourly_breakdown(trades)

    # ── Overall summary ────────────────────────────────────────────────────────
    wins  = sum(1 for t in trades if t.outcome in ("win", "be_close"))
    net_r = round(sum(t.pnl_r for t in trades), 2)
    wr    = round(100 * wins / len(trades), 1) if trades else 0.0
    avg_r = round(net_r / len(trades), 4) if trades else 0.0
    print(f"\n  Overall (no filter):  {len(trades)} trades  WR={wr}%  Net={net_r:+.2f}R  Avg={avg_r:+.4f}R")

    # ── Current window performance ─────────────────────────────────────────────
    cur_trades = [t for t in trades if any(s <= t.hour < e for s, e in cur_windows)]
    if cur_trades:
        cw   = sum(1 for t in cur_trades if t.outcome in ("win", "be_close"))
        cn   = round(sum(t.pnl_r for t in cur_trades), 2)
        cwr  = round(100 * cw / len(cur_trades), 1)
        cavg = round(cn / len(cur_trades), 4)
        win_str = ", ".join(f"{s}–{e}h" for s, e in cur_windows)
        print(f"  Current window ({win_str}):  {len(cur_trades)} trades  WR={cwr}%  Net={cn:+.2f}R  Avg={cavg:+.4f}R")

    # ── Recommendation ────────────────────────────────────────────────────────
    windows = recommend_windows(rows)
    print(f"\n{_HR}")
    print(f"  Recommended session windows for {pair}:")
    for s, e in windows:
        print(f"    {s:02d}:00–{e:02d}:00 UTC")
    print(f"\n  Add to session_filter.py:")
    print(f'    "{pair}": {windows},')

    # ── Projected improvement ─────────────────────────────────────────────────
    proj = [t for t in trades if any(s <= t.hour < e for s, e in windows)]
    if proj:
        pw   = sum(1 for t in proj if t.outcome in ("win", "be_close"))
        pn   = round(sum(t.pnl_r for t in proj), 2)
        pwr  = round(100 * pw / len(proj), 1)
        pavg = round(pn / len(proj), 4)
        print(f"\n  Projected (recommended windows):  {len(proj)} trades  WR={pwr}%  Net={pn:+.2f}R  Avg={pavg:+.4f}R")

    print(f"{_HR}\n")


asyncio.run(main())
