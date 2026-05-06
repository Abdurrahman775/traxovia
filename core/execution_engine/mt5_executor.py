"""core/execution_engine/mt5_executor.py — MT5 bridge HTTP client."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

import httpx


class BridgeError(Exception):
    pass

# Legacy alias used by test_mt5_executor.py
MT5ExecutorError = BridgeError


@dataclass
class OrderOpenResult:
    ticket:      int
    symbol:      str
    direction:   str
    lot_size:    float
    open_price:  float
    stop_loss:   float
    take_profit: float
    comment:     str

# Legacy alias used by test_mt5_executor.py
OrderResult = OrderOpenResult


@dataclass
class OrderCloseResult:
    ticket:      int
    close_price: float
    profit:      float
    comment:     str

# Legacy alias
CloseResult = OrderCloseResult


def _sign(method: str, path: str, body: str = "") -> dict:
    api_key = os.getenv("MT5_BRIDGE_API_KEY", "")
    ts      = str(int(time.time()))
    message = (method.upper() + path + ts + body).encode()
    sig     = hmac.new(api_key.encode(), message, hashlib.sha256).hexdigest()
    return {
        "X-Api-Key":    api_key,
        "X-Timestamp":  ts,
        "X-Signature":  sig,
        "Content-Type": "application/json",
    }


async def _post(path: str, payload: str) -> httpx.Response:
    """Internal HTTP POST to the MT5 bridge — extracted so tests can mock it."""
    url = os.getenv("MT5_BRIDGE_PRIMARY_URL", "http://127.0.0.1:8001")
    headers = _sign("POST", path, payload)
    async with httpx.AsyncClient() as client:
        return await client.post(f"{url}{path}", headers=headers, content=payload)


async def open_order(
    symbol: str,
    direction: str,
    lot_size: float,
    stop_loss: float,
    take_profit: float,
    comment: str = "TradingAI_V3",
) -> OrderOpenResult:
    path = "/order/open"
    body = json.dumps({
        "symbol": symbol, "direction": direction, "lot_size": lot_size,
        "stop_loss": stop_loss, "take_profit": take_profit, "comment": comment,
    })
    resp = await _post(path, body)
    if resp.status_code not in (200, 201):
        raise BridgeError(f"{resp.status_code}: {resp.text}")
    d = resp.json()
    return OrderOpenResult(
        ticket=d["ticket"], symbol=d["symbol"], direction=d["direction"],
        lot_size=d["lot_size"], open_price=d["open_price"],
        stop_loss=d["stop_loss"], take_profit=d["take_profit"], comment=d["comment"],
    )


async def close_order(ticket: int, lot_size: float | None = None) -> OrderCloseResult:
    path    = "/order/close"
    payload: dict = {"ticket": ticket}
    if lot_size is not None:
        payload["lot_size"] = lot_size
    body = json.dumps(payload)
    resp = await _post(path, body)
    if resp.status_code not in (200, 201):
        raise BridgeError(f"{resp.status_code}: {resp.text}")
    d = resp.json()
    return OrderCloseResult(
        ticket=d["ticket"], close_price=d["close_price"],
        profit=d["profit"], comment=d["comment"],
    )
