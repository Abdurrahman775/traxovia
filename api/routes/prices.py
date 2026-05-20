"""
api/routes/prices.py — Live bid prices for the ticker.
"""
import asyncio
from fastapi import APIRouter, Depends
from api.auth import get_current_user

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False

router = APIRouter(tags=["prices"])
PAIRS  = ["USDJPY", "XAUUSD"]


def _get_bid_sync(pair: str) -> tuple[str, float] | None:
    if not _MT5_AVAILABLE or not mt5.initialize():
        return None
    tick = mt5.symbol_info_tick(pair)
    if tick is None:
        return None
    return pair, round(tick.bid, 5)


@router.get("/prices")
async def get_prices(user=Depends(get_current_user)):
    results = await asyncio.gather(*[asyncio.to_thread(_get_bid_sync, p) for p in PAIRS])
    return {pair: price for r in results if r is not None for pair, price in [r]}
