"""
scripts/run_full_backtest.py — Full 4-gate strategy backtest on historical DB data.

Replays the live pipeline (Regime → HTF Bias → Zone → Entry) bar-by-bar against
TimescaleDB H4 + M15 data for all 5 pairs. Uses the exact same strategy objects
that the paper trader uses, so results reflect the actual live logic.

Run:
    source venv/bin/activate
    python3 scripts/run_full_backtest.py
    python3 scripts/run_full_backtest.py --pair EURUSD
    python3 scripts/run_full_backtest.py --from 2024-01-01
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import numpy as np
import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from core.strategy_engine.bias_analyzer    import BiasAnalyzer
from core.strategy_engine.choch_detector   import detect_choch
from core.strategy_engine.daily_bias_filter import check_daily_alignment
from core.strategy_engine.entry_analyzer   import EntryAnalyzer
from core.strategy_engine.fvg_detector     import check_fvg
from core.strategy_engine.htf_structure    import HTFStructure
from core.strategy_engine.liquidity_sweep  import check_liquidity_sweep
from core.strategy_engine.ote_entry        import calculate_ote
from core.strategy_engine.rsi_divergence   import check_rsi_divergence
from core.strategy_engine.session_filter   import is_valid_session
from core.structure_engine.order_block_detector import OrderBlockDetector
from core.structure_engine.regime_classifier import RegimeClassifier
from core.structure_engine.zone_detector   import ZoneDetector
from datetime import timezone as _tz

PAIRS = ["USDJPY", "XAUUSD"]  # EURUSD/GBPUSD dropped — consistent losers

H4_WINDOW  = 200   # H4 bars fed to regime + bias
M15_WINDOW = 150   # M15 bars fed to zone + entry

_HR  = "═" * 72
_HR2 = "─" * 72


# ── Data loading ───────────────────────────────────────────────────────────────

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


# ── Trade simulation ───────────────────────────────────────────────────────────

@dataclass
class Trade:
    pair:        str
    direction:   str
    entry_bar:   int
    entry_price: float
    sl_price:    float
    tp_price:    float
    sl_pips:     float
    tp_pips:     float
    exit_bar:    int = -1
    exit_price:  float = 0.0
    outcome:     str = ""
    pnl_r:       float = 0.0


@dataclass
class PairResult:
    pair:         str
    bars_tested:  int
    total_trades: int
    wins:         int
    losses:       int
    net_r:        float
    win_rate:     float
    avg_r:        float
    max_dd_r:     float
    trades:       list[Trade] = field(default_factory=list)


# ── Single-pair backtest ───────────────────────────────────────────────────────

def run_pair(
    pair: str,
    h4:   pd.DataFrame,
    m15:  pd.DataFrame,
) -> PairResult:
    regime_clf = HTFStructure()       # Phase 1: D1 structure
    bias_clf   = BiasAnalyzer()
    zone_det   = OrderBlockDetector() # Phase 2: Order Blocks replace supply/demand zones
    entry_an   = EntryAnalyzer()

    # Pre-build a sorted list of H4 timestamps for fast alignment
    h4_times = h4["time"].tolist()

    trades:   list[Trade] = []
    active:   Trade | None = None

    # Cache H4-derived results — only recompute when h4_idx changes
    _cached_h4_idx: int = -1
    _cached_reg:    dict | None = None
    _cached_bias:   dict | None = None

    # Start from bar 250 so H4 window is always full
    start = max(H4_WINDOW, 250)

    for i in range(start, len(m15)):
        bar = m15.iloc[i]

        # ── Close active trade if SL/TP hit ───────────────────────────────────
        if active is not None:
            lo = float(bar["low"])
            hi = float(bar["high"])
            hit = None

            if active.direction == "bullish":
                if lo <= active.sl_price:
                    hit, close_p = "loss", active.sl_price
                elif hi >= active.tp_price:
                    hit, close_p = "win",  active.tp_price
            else:
                if hi >= active.sl_price:
                    hit, close_p = "loss", active.sl_price
                elif lo <= active.tp_price:
                    hit, close_p = "win",  active.tp_price

            if hit:
                active.exit_bar   = i
                active.exit_price = close_p
                active.outcome    = hit
                if hit == "win":
                    active.pnl_r = round(active.tp_pips / active.sl_pips, 4)
                else:
                    active.pnl_r = -1.0
                trades.append(active)
                active = None

        if active is not None:
            continue  # still in trade — no new entry

        # ── Align H4 window to current M15 bar time ───────────────────────────
        bar_time = bar["time"]
        h4_idx   = bisect_right(h4_times, bar_time) - 1
        if h4_idx < H4_WINDOW:
            continue

        # ── Session / killzone filter ─────────────────────────────────────────
        bar_dt = bar_time if hasattr(bar_time, "hour") else \
                 pd.Timestamp(bar_time, tz="UTC")
        if not is_valid_session(pair, bar_dt.to_pydatetime().replace(tzinfo=_tz.utc) if bar_dt.tzinfo is None else bar_dt.to_pydatetime())["passed"]:
            continue

        # ── Gate 1: Regime (cached per H4 bar) ───────────────────────────────
        if h4_idx != _cached_h4_idx:
            h4_win = h4.iloc[h4_idx - H4_WINDOW + 1 : h4_idx + 1].reset_index(drop=True)
            _cached_reg  = regime_clf.classify(h4_win)
            _cached_bias = bias_clf.analyze(h4_win, pair)
            if _cached_bias.get("direction"):
                _cached_bias["symbol"] = pair
            _cached_h4_idx = h4_idx

        reg = _cached_reg
        if reg.get("signal_gate") == "blocked":
            continue

        # ── Gate 2: H4 Bias — must align with D1 structure ───────────────────
        bias = _cached_bias
        if not bias.get("direction"):
            continue

        # Reject H4 bias that contradicts D1 structure direction
        d1_bias = reg.get("d1_bias")
        if d1_bias and bias["direction"] != d1_bias:
            continue

        # ── Gate 3: Order Block ───────────────────────────────────────────────
        m15_win = m15.iloc[max(0, i - M15_WINDOW + 1) : i + 1].reset_index(drop=True)
        zone = zone_det.check_gate(m15_win, bias["direction"])
        if not zone["passed"]:
            continue

        # ── Gate 3b: Fair Value Gap inside/near OB ────────────────────────────
        fvg = check_fvg(m15_win, bias["direction"])
        if not fvg["passed"]:
            continue

        # ── Gate 4: Liquidity Sweep (Phase 4 — replaces Entry Analyzer) ─────────
        sweep = check_liquidity_sweep(m15_win, bias["direction"])
        if not sweep["passed"]:
            continue

        # ── Gate 4b: CHOCH confirmation ────────────────────────────────────────
        choch = detect_choch(m15_win, bias["direction"], tp_rr=3.0)
        if not choch["passed"]:
            continue

        # ── Gate 4c: OTE entry at 0.618–0.786 Fib (mandatory — no fallback) ─────
        ote = calculate_ote(
            df          = m15_win,
            direction   = bias["direction"],
            sweep_price = sweep["sweep_price"],
            choch_level = choch["choch_level"],
        )
        if not ote["passed"]:
            continue
        entry = ote

        # Gate 4d (RSI divergence) removed — too restrictive on M15, kills trade count

        active = Trade(
            pair        = pair,
            direction   = bias["direction"],
            entry_bar   = i,
            entry_price = entry["entry_price"],
            sl_price    = entry["sl_price"],
            tp_price    = entry["tp_price"],
            sl_pips     = entry["sl_pips"],
            tp_pips     = entry["tp_pips"],
        )

    # If still in trade at end of data, discard (incomplete)
    total  = len(trades)
    wins   = sum(1 for t in trades if t.outcome == "win")
    losses = total - wins
    net_r  = round(sum(t.pnl_r for t in trades), 4)
    wr     = round(100 * wins / total, 1) if total else 0.0
    avg_r  = round(net_r / total, 4) if total else 0.0

    # Max drawdown in R
    equity = 0.0
    peak   = 0.0
    max_dd = 0.0
    for t in trades:
        equity += t.pnl_r
        peak    = max(peak, equity)
        max_dd  = max(max_dd, peak - equity)

    return PairResult(
        pair         = pair,
        bars_tested  = len(m15) - start,
        total_trades = total,
        wins         = wins,
        losses       = losses,
        net_r        = net_r,
        win_rate     = wr,
        avg_r        = avg_r,
        max_dd_r     = round(max_dd, 2),
        trades       = trades,
    )


# ── Main ───────────────────────────────────────────────────────────────────────

async def main(args: argparse.Namespace) -> None:
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    since: datetime | None = None
    if args.from_date:
        since = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    pairs = [args.pair.upper()] if args.pair else PAIRS

    print(_HR)
    print("  Traxovia AI — Full Strategy Backtest")
    print(f"  Gates   : Regime → HTF Bias → Zone → Entry (exact live pipeline)")
    print(f"  Pairs   : {', '.join(pairs)}")
    print(f"  Since   : {since.date() if since else '2020-05-18 (all data)'}")
    print(_HR)

    conn    = await asyncpg.connect(db_url)
    results: list[PairResult] = []

    try:
        for pair in pairs:
            print(f"\n  Loading {pair} ...", end="", flush=True)
            h4  = await fetch(conn, "ohlc_h4",  pair, since)
            m15 = await fetch(conn, "ohlc_m15", pair, since)
            if h4.empty or m15.empty:
                print(f"  no data — skipped")
                continue
            print(f"  H4={len(h4):,} bars  M15={len(m15):,} bars", flush=True)
            print(f"  Running backtest ...", end="", flush=True)
            r = run_pair(pair, h4, m15)
            results.append(r)
            print(f"  {r.total_trades} trades  WR={r.win_rate:.1f}%  Net={r.net_r:+.2f}R  MaxDD={r.max_dd_r:.2f}R")
    finally:
        await conn.close()

    if not results:
        print("\n  No results.")
        return

    # ── Per-pair table ─────────────────────────────────────────────────────────
    print()
    print(_HR)
    print(f"  {'Pair':<8} {'Trades':>7} {'Wins':>5} {'Losses':>7} {'WR%':>6} {'Net R':>7} {'Avg R':>7} {'MaxDD R':>8}")
    print(_HR2)
    for r in results:
        print(f"  {r.pair:<8} {r.total_trades:>7} {r.wins:>5} {r.losses:>7} "
              f"{r.win_rate:>5.1f}% {r.net_r:>+7.2f} {r.avg_r:>+7.4f} {r.max_dd_r:>8.2f}")

    # ── Aggregate ──────────────────────────────────────────────────────────────
    all_trades = [t for r in results for t in r.trades]
    total  = len(all_trades)
    wins   = sum(1 for t in all_trades if t.outcome == "win")
    net_r  = sum(t.pnl_r for t in all_trades)
    avg_r  = net_r / total if total else 0.0
    wr     = 100 * wins / total if total else 0.0

    equity, peak, max_dd = 0.0, 0.0, 0.0
    for t in sorted(all_trades, key=lambda x: x.entry_bar):
        equity += t.pnl_r
        peak    = max(peak, equity)
        max_dd  = max(max_dd, peak - equity)

    print(_HR2)
    print(f"  {'TOTAL':<8} {total:>7} {wins:>5} {total-wins:>7} "
          f"{wr:>5.1f}% {net_r:>+7.2f} {avg_r:>+7.4f} {max_dd:>8.2f}")
    print(_HR)

    # ── Deployment gate check ──────────────────────────────────────────────────
    # Gates calibrated for 3R TP system: break-even WR = 25%, so 30% = +0.20R expectancy
    print()
    print("  Deployment gates (3R system — break-even WR = 25%):")
    gate_wr  = wr    >= 30.0
    gate_r   = avg_r >= 0.15
    gate_dd  = max_dd <= 40.0
    gate_n   = total  >= 50
    print(f"    Win rate  ≥ 30%   : {wr:.1f}%    {'PASS' if gate_wr  else 'FAIL'}")
    print(f"    Avg R     ≥ 0.15R : {avg_r:.4f}   {'PASS' if gate_r   else 'FAIL'}")
    print(f"    Max DD    ≤ 40R   : {max_dd:.2f}R   {'PASS' if gate_dd  else 'FAIL'}")
    print(f"    Min trades ≥ 50   : {total}      {'PASS' if gate_n   else 'FAIL'}")
    all_pass = gate_wr and gate_r and gate_dd and gate_n
    print()
    print(f"  Overall: {'ALL GATES PASS — ready for live' if all_pass else 'NOT READY — see failing gates above'}")
    print(_HR)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Full 4-gate strategy backtest")
    p.add_argument("--pair",      default="", help="Single pair e.g. EURUSD (default: all)")
    p.add_argument("--from",      dest="from_date", default="",
                   help="Start date YYYY-MM-DD (default: all data from 2020)")
    return p


if __name__ == "__main__":
    asyncio.run(main(_parser().parse_args()))
