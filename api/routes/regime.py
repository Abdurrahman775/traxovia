"""
api/routes/regime.py — Live regime status for all pairs.
Reads H4 candles from the MT5 bridge and runs RegimeClassifier.
Falls back to a degraded response if the bridge is unreachable.
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

_OFFLINE = {"regime": "bridge_offline", "adx": 0.0, "atr_ratio": 0.0, "signal_gate": "blocked"}
_UNKNOWN = {"regime": "unknown",        "adx": 0.0, "atr_ratio": 0.0, "signal_gate": "blocked"}


@router.get("/regime/current")
async def regime_current(user=Depends(get_current_user)):
    bridge = os.getenv("MT5_BRIDGE_URL", os.getenv("MT5_BRIDGE_PRIMARY_URL", "http://127.0.0.1:8001"))
    result: dict = {}
    bridge_reachable = False

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            for pair in PAIRS:
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
        for pair in PAIRS:
            result.setdefault(pair, {**_OFFLINE})

    return {"pairs": result, "bridge_online": bridge_reachable}
