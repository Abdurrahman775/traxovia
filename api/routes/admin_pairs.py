"""
api/routes/admin_pairs.py — Admin: manage trading pairs & run per-pair backtests.

Endpoints
─────────
GET    /admin/pairs                   list all managed pairs
POST   /admin/pairs                   add a new pair
PATCH  /admin/pairs/{symbol}          update sessions / active flag / notes
DELETE /admin/pairs/{symbol}          remove pair (only if no strategy data depends on it)
POST   /admin/pairs/{symbol}/test     run full backtest on H4+M15 data from DB → store result
GET    /admin/pairs/{symbol}/test     return last stored test result
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from api.auth import get_current_user
from database.connection import get_db

logger = logging.getLogger(__name__)

# Add project root so strategy modules are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

router = APIRouter(prefix="/admin/pairs", tags=["admin"])

_SYMBOL_RE = re.compile(r"^[A-Z]{3,10}$")


# ── helpers ──────────────────────────────────────────────────────────────────

def _require_admin(user):
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin access required")


async def _require_admin_live(user, db):
    _require_admin(user)
    ok = await db.fetchval("SELECT is_admin FROM users WHERE id=$1::uuid", user["sub"])
    if not ok:
        raise HTTPException(403, "Admin access required")


# ── schemas ──────────────────────────────────────────────────────────────────

class PairCreate(BaseModel):
    symbol:          str
    display_name:    str = ""
    session_windows: list[list[int]] | None = None  # [[start_h, end_h], ...]
    notes:           str = ""

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        v = v.strip().upper()
        if not _SYMBOL_RE.match(v):
            raise ValueError("Symbol must be 3-10 uppercase letters")
        return v

    @field_validator("session_windows")
    @classmethod
    def validate_windows(cls, v):
        if v is None:
            return v
        for w in v:
            if len(w) != 2 or not (0 <= w[0] < 24) or not (0 < w[1] <= 24) or w[0] >= w[1]:
                raise ValueError("Each window must be [start_hour, end_hour] with 0≤start<end≤24")
        return v


class PairUpdate(BaseModel):
    display_name:    str | None = None
    is_active:       bool | None = None
    session_windows: list[list[int]] | None = None
    notes:           str | None = None

    @field_validator("session_windows")
    @classmethod
    def validate_windows(cls, v):
        if v is None:
            return v
        for w in v:
            if len(w) != 2 or not (0 <= w[0] < 24) or not (0 < w[1] <= 24) or w[0] >= w[1]:
                raise ValueError("Each window must be [start_hour, end_hour] with 0≤start<end≤24")
        return v


# ── routes ───────────────────────────────────────────────────────────────────

@router.get("")
async def list_pairs(
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    rows = await db.fetch(
        """
        SELECT symbol, display_name, is_active, session_windows,
               added_at, last_tested_at, test_result, notes
        FROM   managed_pairs
        ORDER  BY symbol
        """
    )
    return [
        {
            "symbol":          r["symbol"],
            "display_name":    r["display_name"],
            "is_active":       r["is_active"],
            "session_windows": json.loads(r["session_windows"]) if r["session_windows"] else None,
            "added_at":        r["added_at"].isoformat() if r["added_at"] else None,
            "last_tested_at":  r["last_tested_at"].isoformat() if r["last_tested_at"] else None,
            "test_result":     json.loads(r["test_result"]) if r["test_result"] else None,
            "notes":           r["notes"],
        }
        for r in rows
    ]


@router.post("", status_code=201)
async def add_pair(
    body: PairCreate,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    await _require_admin_live(user, db)

    existing = await db.fetchval(
        "SELECT 1 FROM managed_pairs WHERE symbol=$1", body.symbol
    )
    if existing:
        raise HTTPException(409, f"Pair '{body.symbol}' already exists")

    windows_json = json.dumps(body.session_windows) if body.session_windows else None
    await db.execute(
        """
        INSERT INTO managed_pairs
            (symbol, display_name, is_active, session_windows, added_by, notes)
        VALUES ($1,$2,TRUE,$3,$4::uuid,$5)
        """,
        body.symbol, body.display_name or body.symbol,
        windows_json, user["sub"], body.notes,
    )
    logger.info("Admin %s added pair %s", user.get("email"), body.symbol)
    return {"symbol": body.symbol, "created": True}


@router.patch("/{symbol}")
async def update_pair(
    symbol: str,
    body: PairUpdate,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    await _require_admin_live(user, db)
    symbol = symbol.upper()

    row = await db.fetchrow(
        "SELECT symbol FROM managed_pairs WHERE symbol=$1", symbol
    )
    if not row:
        raise HTTPException(404, f"Pair '{symbol}' not found")

    sets, params, idx = [], [], 1
    if body.display_name is not None:
        sets.append(f"display_name=${idx}");   params.append(body.display_name); idx += 1
    if body.is_active is not None:
        sets.append(f"is_active=${idx}");      params.append(body.is_active);    idx += 1
    if body.session_windows is not None:
        sets.append(f"session_windows=${idx}"); params.append(json.dumps(body.session_windows)); idx += 1
    if body.notes is not None:
        sets.append(f"notes=${idx}");          params.append(body.notes);        idx += 1

    if not sets:
        return {"symbol": symbol, "updated": False, "reason": "no fields changed"}

    params.append(symbol)
    await db.execute(
        f"UPDATE managed_pairs SET {', '.join(sets)} WHERE symbol=${idx}",
        *params,
    )
    return {"symbol": symbol, "updated": True}


@router.delete("/{symbol}", status_code=200)
async def delete_pair(
    symbol: str,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    await _require_admin_live(user, db)
    symbol = symbol.upper()

    row = await db.fetchrow("SELECT symbol FROM managed_pairs WHERE symbol=$1", symbol)
    if not row:
        raise HTTPException(404, f"Pair '{symbol}' not found")

    await db.execute("DELETE FROM managed_pairs WHERE symbol=$1", symbol)
    logger.info("Admin %s deleted pair %s", user.get("email"), symbol)
    return {"symbol": symbol, "deleted": True}


# ── Backtest runner ───────────────────────────────────────────────────────────

H4_WINDOW  = 200
M15_WINDOW = 150


async def _run_backtest_for_pair(symbol: str, db) -> dict:
    """Run the full 4-gate strategy backtest on DB data for one pair."""
    # Import here to avoid top-level heavy imports on API startup
    import pandas as pd
    import numpy as np
    from bisect import bisect_right as bsr

    from core.strategy_engine.bias_analyzer    import BiasAnalyzer
    from core.strategy_engine.choch_detector   import detect_choch
    from core.strategy_engine.fvg_detector     import check_fvg
    from core.strategy_engine.htf_structure    import HTFStructure
    from core.strategy_engine.session_filter   import is_valid_session
    from core.structure_engine.order_block_detector import OrderBlockDetector

    # Fetch H4 + M15 data from DB
    h4_rows = await db.fetch(
        "SELECT time,open,high,low,close,volume FROM ohlc_h4 WHERE symbol=$1 ORDER BY time ASC",
        symbol,
    )
    m15_rows = await db.fetch(
        "SELECT time,open,high,low,close,volume FROM ohlc_m15 WHERE symbol=$1 ORDER BY time ASC",
        symbol,
    )

    if len(h4_rows) < H4_WINDOW + 50:
        return {"status": "error", "error": f"Not enough H4 data for {symbol} ({len(h4_rows)} bars — need ≥{H4_WINDOW+50})"}
    if len(m15_rows) < 500:
        return {"status": "error", "error": f"Not enough M15 data for {symbol} ({len(m15_rows)} bars — need ≥500)"}

    cols = ["time", "open", "high", "low", "close", "volume"]
    h4  = pd.DataFrame(h4_rows,  columns=cols)
    m15 = pd.DataFrame(m15_rows, columns=cols)
    for c in ["open", "high", "low", "close"]:
        h4[c]  = h4[c].astype(float)
        m15[c] = m15[c].astype(float)

    # Run pair backtest (same logic as scripts/run_full_backtest.py)
    regime_clf = HTFStructure()
    bias_clf   = BiasAnalyzer()
    zone_det   = OrderBlockDetector()

    h4_times       = h4["time"].tolist()
    trades         = []
    active         = None
    _cached_h4_idx = -1
    _cached_reg    = None
    _cached_bias   = None

    start = max(H4_WINDOW, 250)

    for i in range(start, len(m15)):
        bar = m15.iloc[i]

        # close active trade
        if active is not None:
            lo, hi = float(bar["low"]), float(bar["high"])
            if not active.get("half_closed"):
                if active["direction"] == "bullish" and hi >= active["one_r"]:
                    active["half_closed"] = True; active["sl"] = active["entry"]
                elif active["direction"] == "bearish" and lo <= active["one_r"]:
                    active["half_closed"] = True; active["sl"] = active["entry"]

            hit = None
            if active["direction"] == "bullish":
                if lo <= active["sl"]:   hit, cp = ("be" if active.get("half_closed") else "loss"), active["sl"]
                elif hi >= active["tp"]: hit, cp = "win", active["tp"]
            else:
                if hi >= active["sl"]:   hit, cp = ("be" if active.get("half_closed") else "loss"), active["sl"]
                elif lo <= active["tp"]: hit, cp = "win", active["tp"]

            if hit:
                if hit == "win":    pnl = round(active["tp_pips"] / active["sl_pips"], 4)
                elif hit == "be":   pnl = 0.0
                else:               pnl = -1.0
                trades.append({"outcome": hit, "pnl_r": pnl,
                                "direction": active["direction"],
                                "entry": active["entry"]})
                active = None

        if active is not None:
            continue

        bar_time = bar["time"]
        h4_idx   = bsr(h4_times, bar_time) - 1
        if h4_idx < H4_WINDOW:
            continue

        # Session filter
        bar_dt = bar_time if hasattr(bar_time, "hour") else pd.Timestamp(bar_time, tz="UTC")
        bdt = bar_dt.to_pydatetime()
        if bdt.tzinfo is None:
            bdt = bdt.replace(tzinfo=timezone.utc)
        if not is_valid_session(symbol, bdt)["passed"]:
            continue

        # Gate 1 + 2 (cached)
        if h4_idx != _cached_h4_idx:
            h4_win = h4.iloc[h4_idx - H4_WINDOW + 1 : h4_idx + 1].reset_index(drop=True)
            _cached_reg  = regime_clf.classify(h4_win)
            _cached_bias = bias_clf.analyze(h4_win, symbol)
            if _cached_bias.get("direction"):
                _cached_bias["symbol"] = symbol
            _cached_h4_idx = h4_idx

        if _cached_reg.get("signal_gate") == "blocked":
            continue
        bias = _cached_bias
        if not bias.get("direction"):
            continue
        d1_bias = _cached_reg.get("d1_bias")
        if d1_bias and bias["direction"] != d1_bias:
            continue

        # Gate 3: OB + FVG
        m15_win = m15.iloc[max(0, i - M15_WINDOW + 1) : i + 1].reset_index(drop=True)
        if not zone_det.check_gate(m15_win, bias["direction"])["passed"]:
            continue
        if not check_fvg(m15_win, bias["direction"])["passed"]:
            continue

        # Gate 4: CHOCH
        choch = detect_choch(m15_win, bias["direction"], tp_rr=3.0)
        if not choch["passed"]:
            continue

        one_r = 2 * choch["entry_price"] - choch["sl_price"]
        active = {
            "direction": bias["direction"],
            "entry":     choch["entry_price"],
            "sl":        choch["sl_price"],
            "tp":        choch["tp_price"],
            "sl_pips":   choch["sl_pips"],
            "tp_pips":   choch["tp_pips"],
            "one_r":     one_r,
            "half_closed": False,
        }

    # Summarise
    n     = len(trades)
    wins  = sum(1 for t in trades if t["outcome"] in ("win", "be"))
    net_r = round(sum(t["pnl_r"] for t in trades), 2)
    wr    = round(100 * wins / n, 1) if n else 0.0
    avg_r = round(net_r / n, 3) if n else 0.0

    equity, peak, max_dd = 0.0, 0.0, 0.0
    for t in trades:
        equity += t["pnl_r"]
        peak    = max(peak, equity)
        max_dd  = max(max_dd, peak - equity)

    # Gate pass / fail
    gates = {
        "win_rate":   {"val": wr,    "pass": wr >= 50.0,    "threshold": "≥50%"},
        "avg_r":      {"val": avg_r, "pass": avg_r >= 0.15, "threshold": "≥0.15R"},
        "max_dd":     {"val": round(max_dd, 2), "pass": max_dd <= 10.0, "threshold": "≤10R"},
        "trade_count":{"val": n,     "pass": n >= 50,        "threshold": "≥50 trades"},
    }
    all_pass = all(g["pass"] for g in gates.values())

    return {
        "status":      "pass" if all_pass else ("insufficient_data" if n < 50 else "fail"),
        "symbol":      symbol,
        "trades":      n,
        "wins":        wins,
        "losses":      n - wins,
        "win_rate":    wr,
        "net_r":       net_r,
        "avg_r":       avg_r,
        "max_dd_r":    round(max_dd, 2),
        "gates":       gates,
        "all_gates_pass": all_pass,
        "h4_bars":     len(h4),
        "m15_bars":    len(m15),
    }


@router.post("/{symbol}/test")
async def test_pair(
    symbol: str,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Run a full backtest on all historical DB data for this pair.
    Stores the result and returns it.  May take 10–30s for large datasets.
    """
    await _require_admin_live(user, db)
    symbol = symbol.upper()

    row = await db.fetchrow("SELECT symbol FROM managed_pairs WHERE symbol=$1", symbol)
    if not row:
        raise HTTPException(404, f"Pair '{symbol}' not found in managed_pairs")

    # Mark as running
    await db.execute(
        "UPDATE managed_pairs SET last_tested_at=$1, test_result=$2 WHERE symbol=$3",
        datetime.now(timezone.utc),
        json.dumps({"status": "running"}),
        symbol,
    )

    try:
        result = await _run_backtest_for_pair(symbol, db)
    except Exception as exc:
        logger.exception("Backtest failed for %s: %s", symbol, exc)
        result = {"status": "error", "error": str(exc)}

    await db.execute(
        "UPDATE managed_pairs SET test_result=$1, last_tested_at=$2 WHERE symbol=$3",
        json.dumps(result),
        datetime.now(timezone.utc),
        symbol,
    )
    return result


@router.get("/{symbol}/test")
async def get_test_result(
    symbol: str,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    _require_admin(user)
    symbol = symbol.upper()
    row = await db.fetchrow(
        "SELECT test_result, last_tested_at FROM managed_pairs WHERE symbol=$1", symbol
    )
    if not row:
        raise HTTPException(404, f"Pair '{symbol}' not found")
    if not row["test_result"]:
        return {"status": "never_tested"}
    return {
        **json.loads(row["test_result"]),
        "last_tested_at": row["last_tested_at"].isoformat() if row["last_tested_at"] else None,
    }
