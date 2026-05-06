"""
api/routes/prices.py — Live bid prices for the ticker.
"""
import os
import asyncio
import httpx
from fastapi import APIRouter, Depends
from api.auth import get_current_user
from core.execution_engine.mt5_executor import _sign

router = APIRouter(tags=["prices"])
PAIRS  = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30"]


async def _fetch_price(client: httpx.AsyncClient, bridge: str, pair: str) -> tuple[str, float] | None:
    path = f"/spread/{pair}"
    headers = _sign("GET", path)
    headers.pop("Content-Type", None)
    try:
        r = await client.get(f"{bridge}{path}", headers=headers)
        if r.status_code == 200:
            return pair, round(r.json().get("bid", 0), 5)
    except Exception:
        pass
    return None


@router.get("/prices")
async def get_prices(user=Depends(get_current_user)):
    bridge = os.getenv("MT5_BRIDGE_PRIMARY_URL", "http://127.0.0.1:8001")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            results = await asyncio.gather(*[_fetch_price(client, bridge, p) for p in PAIRS])
        return {pair: price for r in results if r is not None and not isinstance(r, Exception) for pair, price in [r]}
    except Exception:
        return {}
