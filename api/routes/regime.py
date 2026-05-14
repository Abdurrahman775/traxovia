"""
api/routes/regime.py — Live regime status for all pairs.
Reads H4 candles from the ohlc_h4 DB table and runs RegimeClassifier.
No MT5 dependency — works entirely from stored candle data.
"""
import json
import pandas as pd
from fastapi import APIRouter, Depends
from api.auth import get_current_user
from database.connection import get_db, set_rls_user
from core.structure_engine.regime_classifier import RegimeClassifier

router = APIRouter(tags=["regime"])
_clf = RegimeClassifier()

_FALLBACK_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
_UNKNOWN = {"regime": "unknown", "adx": 0.0, "atr_ratio": 0.0, "signal_gate": "blocked"}


def _normalize(pair: str) -> str:
    return pair.replace("/", "").replace("-", "").upper()


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


@router.get("/regime/current")
async def regime_current(user=Depends(get_current_user), db=Depends(get_db)):
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

    result: dict = {}
    has_data = False

    for pair in pairs:
        bars = await _fetch_h4_from_db(db, pair)
        if bars:
            has_data = True
            df = pd.DataFrame(bars)
            r  = _clf.classify(df)
            result[pair] = {
                "regime":      r["regime"],
                "adx":         round(r["adx"], 2),
                "atr_ratio":   round(min(float(r["atr_ratio"]), 99.99), 2),
                "signal_gate": r["signal_gate"],
            }
        else:
            result[pair] = {**_UNKNOWN}

    return {"pairs": result, "bridge_online": has_data}
