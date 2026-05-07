"""
api/routes/regime.py — Live regime status for all pairs.
Reads H4 candles from the MT5 bridge and runs RegimeClassifier.
Falls back to a degraded response if the bridge is unreachable.
"""
import json
import httpx
import pandas as pd
from fastapi import APIRouter, Depends
from api.auth import get_current_user
from database.connection import get_db, set_rls_user
from config import settings
from core.execution_engine.mt5_executor import _sign
from core.structure_engine.regime_classifier import RegimeClassifier

router = APIRouter(tags=["regime"])
_clf = RegimeClassifier()

_FALLBACK_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]

_OFFLINE = {"regime": "bridge_offline", "adx": 0.0, "atr_ratio": 0.0, "signal_gate": "blocked"}
_UNKNOWN = {"regime": "unknown",        "adx": 0.0, "atr_ratio": 0.0, "signal_gate": "blocked"}


def _normalize(pair: str) -> str:
    """EUR/USD → EURUSD for bridge requests."""
    return pair.replace("/", "").replace("-", "").upper()


@router.get("/regime/current")
async def regime_current(user=Depends(get_current_user), db=Depends(get_db)):
    await set_rls_user(db, user["sub"])

    # Load active pairs from user settings
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

    bridge = settings.mt5_bridge_primary_url or "http://127.0.0.1:8001"
    result: dict = {}
    bridge_reachable = False

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            for pair in pairs:
                path = f"/ohlc/{pair}/H4"
                try:
                    resp = await client.get(
                        f"{bridge}{path}",
                        params={"count": 100},
                        headers=_sign("GET", path),
                    )
                    if resp.status_code == 200:
                        bars = resp.json().get("bars", [])
                        if bars:
                            df = pd.DataFrame(bars)
                            r  = _clf.classify(df)
                            bridge_reachable = True
                            result[pair] = {
                                "regime":      r["regime"],
                                "adx":         round(r["adx"], 2),
                                "atr_ratio":   round(min(float(r["atr_ratio"]), 99.99), 2),
                                "signal_gate": r["signal_gate"],
                            }
                        else:
                            result[pair] = {**_UNKNOWN}
                    else:
                        result[pair] = {**_UNKNOWN}
                except Exception:
                    result.setdefault(pair, {**_OFFLINE})
    except Exception:
        pass

    if not bridge_reachable:
        for pair in pairs:
            result.setdefault(pair, {**_OFFLINE})

    return {"pairs": result, "bridge_online": bridge_reachable}
