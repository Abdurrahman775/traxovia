"""
api/routes/regime.py — Live regime status for all pairs.
Reads H4 candles directly from MT5 and runs RegimeClassifier.
Falls back to a degraded response if MT5 is unavailable.
"""
import asyncio
import json
import pandas as pd
from fastapi import APIRouter, Depends
from api.auth import get_current_user
from database.connection import get_db, set_rls_user
from core.structure_engine.regime_classifier import RegimeClassifier

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False

router = APIRouter(tags=["regime"])
_clf = RegimeClassifier()

_FALLBACK_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
_OFFLINE = {"regime": "mt5_offline", "adx": 0.0, "atr_ratio": 0.0, "signal_gate": "blocked"}
_UNKNOWN = {"regime": "unknown",     "adx": 0.0, "atr_ratio": 0.0, "signal_gate": "blocked"}


def _normalize(pair: str) -> str:
    return pair.replace("/", "").replace("-", "").upper()


def _fetch_h4_sync(pair: str) -> list[dict] | None:
    if not _MT5_AVAILABLE or not mt5.initialize():
        return None
    rates = mt5.copy_rates_from_pos(pair, mt5.TIMEFRAME_H4, 0, 100)
    if rates is None:
        return None
    return [
        {"time": int(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
         "low": float(r["low"]), "close": float(r["close"]), "volume": int(r["tick_volume"])}
        for r in rates
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

    for pair in pairs:
        bars = await asyncio.to_thread(_fetch_h4_sync, pair)
        if bars:
            df = pd.DataFrame(bars)
            r  = _clf.classify(df)
            result[pair] = {
                "regime":      r["regime"],
                "adx":         round(r["adx"], 2),
                "atr_ratio":   round(min(float(r["atr_ratio"]), 99.99), 2),
                "signal_gate": r["signal_gate"],
            }
        else:
            result[pair] = {**(_OFFLINE if not _MT5_AVAILABLE else _UNKNOWN)}

    return {"pairs": result, "mt5_online": _MT5_AVAILABLE}
