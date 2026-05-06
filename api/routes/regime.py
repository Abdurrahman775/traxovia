"""
api/routes/regime.py — Live regime status for all pairs.
Reads from the MT5 bridge (H4 candles) and runs RegimeClassifier.
Falls back to cached DB values if bridge is unreachable.
"""
import os
import httpx
import pandas as pd
from fastapi import APIRouter, Depends
from api.auth import get_current_user
from core.execution_engine.mt5_executor import _sign
from core.structure_engine.regime_classifier import RegimeClassifier

router = APIRouter(tags=["regime"])
_clf   = RegimeClassifier()
PAIRS  = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30"]


@router.get("/regime/current")
async def regime_current(user=Depends(get_current_user)):
    bridge = os.getenv("MT5_BRIDGE_PRIMARY_URL", "http://127.0.0.1:8001")
    result = {}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            for pair in PAIRS:
                path = f"/ohlc/{pair}/H4"
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
                        result[pair] = {"regime": r["regime"], "adx": round(r["adx"], 2)}
                    else:
                        result[pair] = {"regime": "unknown", "adx": 0}
                else:
                    result[pair] = {"regime": "unavailable", "adx": 0}
    except Exception:
        for pair in PAIRS:
            result.setdefault(pair, {"regime": "bridge_offline", "adx": 0})
    return result
