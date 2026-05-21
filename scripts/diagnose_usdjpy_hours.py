"""
scripts/diagnose_usdjpy_hours.py — USDJPY WR breakdown by entry hour.

Runs the full pipeline for USDJPY and prints wins/losses/WR per UTC hour
so we can see exactly which hours are dragging performance.
"""
from __future__ import annotations

import asyncio
import os
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from core.strategy_engine.bias_analyzer    import BiasAnalyzer
from core.strategy_engine.choch_detector   import detect_choch
from core.strategy_engine.fvg_detector     import check_fvg
from core.strategy_engine.htf_structure    import HTFStructure
from core.strategy_engine.session_filter   import is_valid_session
from core.structure_engine.order_block_detector import OrderBlockDetector
from datetime import timezone as _tz

H4_WINDOW  = 200
M15_WINDOW = 150
_HR  = "═" * 60
_HR2 = "─" * 60


async def main() -> None:
    db_url = os.getenv("DATABASE_URL", "")
    conn = await asyncpg.connect(db_url)

    rows = await conn.fetch(
        "SELECT time,open,high,low,close,volume FROM ohlc_h4 WHERE symbol=$1 ORDER BY time", "USDJPY"
    )
    h4 = pd.DataFrame(rows, columns=["time","open","high","low","close","volume"])
    h4[["open","high","low","close"]] = h4[["open","high","low","close"]].astype(float)

    rows = await conn.fetch(
        "SELECT time,open,high,low,close,volume FROM ohlc_m15 WHERE symbol=$1 ORDER BY time", "USDJPY"
    )
    m15 = pd.DataFrame(rows, columns=["time","open","high","low","close","volume"])
    m15[["open","high","low","close"]] = m15[["open","high","low","close"]].astype(float)
    await conn.close()

    regime_clf = HTFStructure()
    bias_clf   = BiasAnalyzer()
    zone_det   = OrderBlockDetector()
    h4_times   = h4["time"].tolist()

    _cached_h4_idx = -1
    _cached_reg    = None
    _cached_bias   = None

    # hour → [pnl_r, ...]
    hour_trades: dict[int, list[float]] = defaultdict(list)

    active      = None
    active_hour = 0
    start = max(H4_WINDOW, 250)

    for i in range(start, len(m15)):
        bar = m15.iloc[i]

        if active is not None:
            lo, hi = float(bar["low"]), float(bar["high"])
            hit = None
            if active["dir"] == "bullish":
                if lo <= active["sl"]:   hit, r = "loss", -1.0
                elif hi >= active["tp"]: hit, r = "win",  round(active["tp_pips"]/active["sl_pips"], 4)
            else:
                if hi >= active["sl"]:   hit, r = "loss", -1.0
                elif lo <= active["tp"]: hit, r = "win",  round(active["tp_pips"]/active["sl_pips"], 4)
            if hit:
                hour_trades[active_hour].append(r)
                active = None
            continue

        bar_time = bar["time"]
        h4_idx   = bisect_right(h4_times, bar_time) - 1
        if h4_idx < H4_WINDOW:
            continue

        bar_dt = bar_time if hasattr(bar_time, "hour") else pd.Timestamp(bar_time, tz="UTC")
        dt_obj = bar_dt.to_pydatetime()
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=_tz.utc)
        if not is_valid_session("USDJPY", dt_obj)["passed"]:
            continue

        if h4_idx != _cached_h4_idx:
            h4_win = h4.iloc[h4_idx - H4_WINDOW + 1 : h4_idx + 1].reset_index(drop=True)
            _cached_reg  = regime_clf.classify(h4_win)
            _cached_bias = bias_clf.analyze(h4_win, "USDJPY")
            if _cached_bias.get("direction"):
                _cached_bias["symbol"] = "USDJPY"
            _cached_h4_idx = h4_idx

        if _cached_reg.get("signal_gate") == "blocked":
            continue
        bias = _cached_bias
        if not bias.get("direction"):
            continue
        d1_bias = _cached_reg.get("d1_bias")
        if d1_bias and bias["direction"] != d1_bias:
            continue

        m15_win = m15.iloc[max(0, i - M15_WINDOW + 1) : i + 1].reset_index(drop=True)
        if not zone_det.check_gate(m15_win, bias["direction"])["passed"]:
            continue
        if not check_fvg(m15_win, bias["direction"])["passed"]:
            continue
        choch = detect_choch(m15_win, bias["direction"], tp_rr=3.0)
        if not choch["passed"]:
            continue

        active_hour = dt_obj.hour
        active = {
            "dir":     bias["direction"],
            "sl":      choch["sl_price"],
            "tp":      choch["tp_price"],
            "sl_pips": choch["sl_pips"],
            "tp_pips": choch["tp_pips"],
        }

    print(_HR)
    print("  USDJPY — Win Rate by Entry Hour (UTC)")
    print(_HR)
    print(f"  {'Hour':>5}  {'Trades':>7}  {'Wins':>5}  {'Losses':>7}  {'WR%':>6}  {'Net R':>7}")
    print(_HR2)

    total_t, total_w = 0, 0
    for hour in sorted(hour_trades):
        results = hour_trades[hour]
        n    = len(results)
        wins = sum(1 for r in results if r > 0)
        net  = sum(results)
        wr   = 100 * wins / n if n else 0
        flag = " ◄ WEAK" if wr < 25 else (" ◄ BEST" if wr >= 40 else "")
        print(f"  {hour:>4}h  {n:>7}  {wins:>5}  {n-wins:>7}  {wr:>5.1f}%  {net:>+7.2f}{flag}")
        total_t += n
        total_w += wins

    print(_HR2)
    total_wr = 100 * total_w / total_t if total_t else 0
    print(f"  {'TOTAL':>5}  {total_t:>7}  {total_w:>5}  {total_t-total_w:>7}  {total_wr:>5.1f}%")
    print(_HR)


asyncio.run(main())
