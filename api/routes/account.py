"""api/routes/account.py — MT5 account info (balance, equity, margin)."""
import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from api.auth import get_current_user

router = APIRouter(tags=["account"])

_BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "http://127.0.0.1:8001")


@router.get("/account")
async def get_account(user=Depends(get_current_user)):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{_BRIDGE_URL}/account")
            r.raise_for_status()
            data = r.json()
            return {
                "login": data.get("login"),
                "balance": data.get("balance"),
                "equity": data.get("equity"),
                "margin": data.get("margin"),
                "currency": data.get("currency"),
                "trade_mode": data.get("trade_mode"),
                "leverage": data.get("leverage"),
                "company": data.get("company"),
                "server": data.get("server"),
            }
    except httpx.RequestError as e:
        raise HTTPException(503, f"MT5 bridge unreachable: {e}")
