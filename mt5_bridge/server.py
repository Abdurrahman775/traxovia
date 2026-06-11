"""mt5_bridge/server.py — MT5 Bridge Server (runs inside Wine Python on Linux).

Exposes a local HTTP API so the Linux Python side can call MetaTrader5
without needing a Windows machine. Only listens on localhost:8001.

How to run (Wine Python, not system Python):
    wine python /home/kira/trading-bot/mt5_bridge/server.py

Managed by systemd: see mt5-bridge.service
Requires: xvfb.service must be running first (virtual display for Wine GUI).
"""
import os
from datetime import datetime, timezone
from typing import Optional

import MetaTrader5 as mt5
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="MT5 Bridge", docs_url=None, redoc_url=None)

# ── Timeframe map ──────────────────────────────────────────────────────────────

_TF = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
    "W1":  mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}

_ACTION = {
    "TRADE_ACTION_DEAL": mt5.TRADE_ACTION_DEAL,
    "TRADE_ACTION_SLTP": mt5.TRADE_ACTION_SLTP,
}
_FILLING = {
    "ORDER_FILLING_FOK":    mt5.ORDER_FILLING_FOK,
    "ORDER_FILLING_IOC":    mt5.ORDER_FILLING_IOC,
    "ORDER_FILLING_RETURN": mt5.ORDER_FILLING_RETURN,
}


def _init():
    if not mt5.initialize():
        raise HTTPException(503, f"MT5 initialize() failed: {mt5.last_error()}")


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    ok = mt5.initialize()
    if not ok:
        return JSONResponse(
            {"status": "error", "error": str(mt5.last_error())}, status_code=503
        )
    info = mt5.account_info()
    return {
        "status":     "ok",
        "account":    info.login if info else None,
        "balance":    info.balance if info else None,
        "currency":   info.currency if info else None,
        "trade_mode": info.trade_mode if info else None,
    }


# ── Initialize / Account ───────────────────────────────────────────────────────

@app.post("/initialize")
def initialize(body: dict = {}):
    login    = body.get("login")
    password = body.get("password")
    server   = body.get("server")
    if login and password and server:
        ok = mt5.initialize(login=int(login), password=str(password), server=str(server))
    else:
        ok = mt5.initialize()
    return {"ok": ok, "error": str(mt5.last_error()) if not ok else None}


@app.get("/account")
def account():
    _init()
    info = mt5.account_info()
    if info is None:
        raise HTTPException(500, f"account_info() returned None: {mt5.last_error()}")
    return {
        "login":      info.login,
        "balance":    info.balance,
        "equity":     info.equity,
        "margin":     info.margin,
        "currency":   info.currency,
        "trade_mode": info.trade_mode,
        "leverage":   info.leverage,
        "company":    info.company,
        "server":     info.server,
    }


# ── Symbol helpers ─────────────────────────────────────────────────────────────

@app.get("/tick/{symbol}")
def tick(symbol: str):
    _init()
    t = mt5.symbol_info_tick(symbol)
    if t is None:
        raise HTTPException(404, f"No tick for {symbol}: {mt5.last_error()}")
    return {"ask": t.ask, "bid": t.bid, "last": t.last, "time": t.time}


@app.get("/symbol_info/{symbol}")
def symbol_info(symbol: str):
    _init()
    info = mt5.symbol_info(symbol)
    if info is None:
        raise HTTPException(404, f"No info for {symbol}: {mt5.last_error()}")
    return {
        "filling_mode": info.filling_mode,
        "spread":       info.spread,
        "digits":       info.digits,
    }


@app.post("/symbol_select/{symbol}")
def symbol_select(symbol: str):
    _init()
    ok = mt5.symbol_select(symbol, True)
    return {"ok": ok}


# ── OHLC rates ─────────────────────────────────────────────────────────────────

@app.get("/rates/{symbol}/{timeframe}")
def rates(symbol: str, timeframe: str, count: int = Query(default=200, ge=1, le=50000)):
    _init()
    tf = _TF.get(timeframe.upper())
    if tf is None:
        raise HTTPException(400, f"Unknown timeframe: {timeframe}")
    mt5.symbol_select(symbol, True)
    raw = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if raw is None:
        raise HTTPException(500, f"copy_rates_from_pos failed: {mt5.last_error()}")
    return [
        {
            "time":        int(r["time"]),
            "open":        float(r["open"]),
            "high":        float(r["high"]),
            "low":         float(r["low"]),
            "close":       float(r["close"]),
            "tick_volume": int(r["tick_volume"]),
            "volume":      int(r["tick_volume"]),
            "spread":      int(r["spread"]),
        }
        for r in raw
    ]


# ── Positions ──────────────────────────────────────────────────────────────────

@app.get("/positions")
def positions(ticket: Optional[int] = None):
    _init()
    result = mt5.positions_get(ticket=ticket) if ticket else mt5.positions_get()
    if result is None:
        return []
    return [
        {
            "ticket":     p.ticket,
            "symbol":     p.symbol,
            "type":       p.type,
            "volume":     p.volume,
            "price_open": p.price_open,
            "sl":         p.sl,
            "tp":         p.tp,
            "profit":     p.profit,
        }
        for p in result
    ]


# ── Order send ─────────────────────────────────────────────────────────────────

@app.post("/order")
def order_send(body: dict):
    _init()
    req = dict(body)

    # Map string constants to MT5 integers
    if isinstance(req.get("action"), str):
        req["action"] = _ACTION[req["action"]]
    if isinstance(req.get("type_filling"), str):
        req["type_filling"] = _FILLING[req["type_filling"]]
    if isinstance(req.get("type_time"), str):
        req["type_time"] = mt5.ORDER_TIME_GTC

    result = mt5.order_send(req)
    if result is None:
        raise HTTPException(500, f"order_send returned None: {mt5.last_error()}")
    return {
        "retcode": result.retcode,
        "order":   result.order,
        "price":   result.price,
        "volume":  result.volume,
        "comment": result.comment,
        "done":    result.retcode == mt5.TRADE_RETCODE_DONE,
    }


# ── Deal history ───────────────────────────────────────────────────────────────

@app.get("/deals")
def deals(from_ts: int, to_ts: int):
    _init()
    from_dt = datetime.fromtimestamp(from_ts, tz=timezone.utc)
    to_dt   = datetime.fromtimestamp(to_ts,   tz=timezone.utc)
    result  = mt5.history_deals_get(from_dt, to_dt) or []
    return [
        {
            "ticket":      d.ticket,
            "position_id": d.position_id,
            "entry":       d.entry,
            "price":       float(d.price),
            "volume":      float(d.volume),
            "symbol":      d.symbol,
        }
        for d in result
    ]


if __name__ == "__main__":
    port = int(os.getenv("MT5_BRIDGE_PORT", "8001"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
