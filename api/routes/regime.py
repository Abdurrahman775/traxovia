"""
api/routes/regime.py — Live D1 market structure status for all pairs.
Reads H4 candles from the ohlc_h4 DB table (or falls back to MT5 bridge)
and runs HTFStructure (Phase 1 ICT).
"""
import json
import os
import httpx
import pandas as pd
from fastapi import APIRouter, Depends
from api.auth import get_current_user
from database.connection import get_db, set_rls_user
from core.strategy_engine.htf_structure import HTFStructure

router = APIRouter(tags=["regime"])
_clf = HTFStructure()

_FALLBACK_PAIRS = ["USDJPY", "XAUUSD"]
_UNKNOWN = {"regime": "unknown", "adx": 0.0, "d1_bias": None, "signal_gate": "blocked"}
_BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "http://127.0.0.1:8001")


def _normalize(pair: str) -> str:
    return pair.replace("/", "").replace("-", "").upper()


async def _check_bridge_health() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{_BRIDGE_URL}/health")
            if r.status_code == 200:
                data = r.json()
                return data.get("status") == "ok"
            return False
    except Exception:
        return False


async def _fetch_h4_from_db(db, pair: str, limit: int = 100) -> list[dict] | None:
    rows = await db.fetch(
        """SELECT time, open, high, low, close, volume
           FROM ohlc_h4
           WHERE symbol = $1
           ORDER BY time DESC
           LIMIT $2""",
        pair, limit,
    )
    if not rows:
        return None
    return [
        {"time": r["time"].timestamp(), "open": float(r["open"]), "high": float(r["high"]),
         "low": float(r["low"]), "close": float(r["close"]),
         "volume": int(r["volume"]) if r["volume"] else 0}
        for r in reversed(rows)
    ]


async def _fetch_h4_from_bridge(pair: str) -> list[dict] | None:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{_BRIDGE_URL}/rates/{pair}/H4", params={"count": 100})
            r.raise_for_status()
            raw = r.json()
            if not raw:
                return None
            return [
                {"time": int(bar["time"]), "open": float(bar["open"]),
                 "high": float(bar["high"]), "low": float(bar["low"]),
                 "close": float(bar["close"]), "volume": int(bar["volume"])}
                for bar in raw
            ]
    except Exception:
        return None


@router.get("/regime/current")
async def regime_current(user=Depends(get_current_user), db=Depends(get_db)):
    try:
        await set_rls_user(db, user["sub"])

        row = await db.fetchrow("SELECT active_pairs FROM users WHERE id=$1", user["sub"])
        raw = row["active_pairs"] if row else None
        if raw:
            try:
                prefs = raw if isinstance(raw, dict) else json.loads(raw)
                pairs = [_normalize(p) for p, enabled in prefs.items() if enabled]
            except Exception:
                pairs = _FALLBACK_PAIRS
        else:
            pairs = _FALLBACK_PAIRS

        if not pairs:
            pairs = _FALLBACK_PAIRS

        bridge_online = await _check_bridge_health()
        result: dict = {}

        for pair in pairs:
            try:
                bars = await _fetch_h4_from_db(db, pair)
                if not bars and bridge_online:
                    bars = await _fetch_h4_from_bridge(pair)
                if bars and len(bars) > 50:  # Need enough data for classification
                    df = pd.DataFrame(bars)
                    r  = _clf.classify(df)
                    raw_gate = r.get("signal_gate", "blocked")
                    if raw_gate == "pass":
                        gate = "reduced" if r.get("regime") == "volatile" else "open"
                    else:
                        gate = "blocked"
                    result[pair] = {
                        "regime":      r.get("regime", "unknown"),
                        "adx":         round(r.get("adx", 0.0), 2),
                        "d1_bias":     r.get("d1_bias"),
                        "d1_bos_level": r.get("d1_bos_level"),
                        "signal_gate": gate,
                    }
                else:
                    result[pair] = {**_UNKNOWN}
            except Exception as e:
                logger.warning(f"Error processing pair {pair}: {e}")
                result[pair] = {**_UNKNOWN}

        return {"pairs": result, "bridge_online": bridge_online}
    
    except Exception as e:
        logger.error(f"Regime endpoint error: {e}")
        # Return fallback data instead of 500 error
        return {
            "pairs": {pair: {**_UNKNOWN} for pair in _FALLBACK_PAIRS}, 
            "bridge_online": False,
            "error": "Failed to load regime data"
        }
