"""
core/execution_engine/mt5_bridge.py — Windows VPS FastAPI bridge server.

Runs on a Windows VPS only. The MetaTrader5 Python library is Windows-exclusive
and cannot be imported on Linux. The Linux server (data_engine, bridge_watchdog,
signal_generator) calls this server over HTTP using the X-Api-Key header.

Launch (on Windows VPS):
    uvicorn core.execution_engine.mt5_bridge:app --host 0.0.0.0 --port 8001 --workers 1

IMPORTANT: run with --workers 1. MetaTrader5 holds a single connection per
process. Multiple workers would each open a separate MT5 terminal, which the
broker does not allow on a single account.

Environment variables (.env on Windows VPS):
    MT5_ACCOUNT        — numeric account number
    MT5_PASSWORD       — account password
    MT5_SERVER         — broker server name, e.g. "Exness-MT5Real8"
    MT5_BRIDGE_API_KEY — shared secret matched against X-Api-Key header
    MT5_BRIDGE_PORT    — port to listen on (default: 8001)
    IS_STANDBY         — "true" on the standby VPS (logged only; no behaviour change)
"""

import os
import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

import MetaTrader5 as mt5
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

MT5_ACCOUNT  = int(os.getenv("MT5_ACCOUNT", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "")
_API_KEY     = os.getenv("MT5_BRIDGE_API_KEY", "")
IS_STANDBY   = os.getenv("IS_STANDBY", "false").lower() == "true"

# MT5 is not thread-safe for init/shutdown. Serialise all calls with this lock.
_mt5_lock = threading.Lock()
_mt5_connected = False


# ── Timeframe map ──────────────────────────────────────────────────────────────

_TF_MAP: dict[str, int] = {
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

# Pips divisor per symbol — converts MT5 spread (points) to pips.
# Most forex at Exness: 5-digit quote → 1 pip = 10 points.
# XAU/USD: 2-decimal quote → spread returned in raw points; caller treats as pips.
_PIP_DIVISOR: dict[str, float] = {
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "USDJPY": 10.0,
    "AUDUSD": 10.0,
    "XAUUSD": 1.0,
}


# ── MT5 connection helpers ─────────────────────────────────────────────────────

def _mt5_init() -> bool:
    """Initialise and log in to MT5. Returns True on success."""
    global _mt5_connected
    with _mt5_lock:
        if not mt5.initialize():
            logger.error("mt5.initialize() failed: %s", mt5.last_error())
            _mt5_connected = False
            return False

        ok = mt5.login(MT5_ACCOUNT, password=MT5_PASSWORD, server=MT5_SERVER)
        if not ok:
            logger.error("mt5.login() failed: %s", mt5.last_error())
            mt5.shutdown()
            _mt5_connected = False
            return False

        info = mt5.account_info()
        logger.info(
            "MT5 connected: account=%d server=%s balance=%.2f %s",
            info.login, info.server, info.balance,
            "(STANDBY)" if IS_STANDBY else "(PRIMARY)",
        )
        _mt5_connected = True
        return True


def _mt5_shutdown() -> None:
    global _mt5_connected
    with _mt5_lock:
        mt5.shutdown()
        _mt5_connected = False
    logger.info("MT5 disconnected.")


def _require_connected() -> None:
    if not _mt5_connected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "MT5 terminal not connected — call POST /mt5/initialize first",
        )


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    ok = await asyncio.to_thread(_mt5_init)
    if not ok:
        logger.warning(
            "MT5 failed to connect on startup — server still accepting requests. "
            "Call POST /mt5/initialize to retry."
        )
    yield
    await asyncio.to_thread(_mt5_shutdown)


# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Trading AI MT5 Bridge",
    version="3.0.0",
    description=(
        "MT5 bridge — runs on Windows VPS. "
        f"{'STANDBY' if IS_STANDBY else 'PRIMARY'} instance."
    ),
    lifespan=lifespan,
)


# ── Authentication ─────────────────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)
_TIMESTAMP_TOLERANCE = 30  # seconds


async def _verify_api_key(
    request: Request,
    key: str = Security(_api_key_header),
) -> None:
    if not _API_KEY:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "MT5_BRIDGE_API_KEY not configured on this server",
        )
    if not key or key != _API_KEY:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Invalid or missing X-Api-Key header",
        )
    # Replay protection: reject requests with a stale or missing timestamp
    ts_header = request.headers.get("X-Timestamp", "")
    try:
        ts = int(ts_header)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid X-Timestamp header")
    if abs(int(time.time()) - ts) > _TIMESTAMP_TOLERANCE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Request timestamp expired")


_auth = Depends(_verify_api_key)


# ── Request / response models ──────────────────────────────────────────────────

class OHLCBar(BaseModel):
    time: int           # POSIX timestamp (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: int
    spread: float       # raw MT5 spread in points


class OHLCResponse(BaseModel):
    symbol: str
    timeframe: str
    count: int
    bars: list[OHLCBar]


class SpreadResponse(BaseModel):
    symbol: str
    spread_points: float
    spread_pips: float
    bid: float
    ask: float
    timestamp: str


class OrderOpenRequest(BaseModel):
    symbol: str
    direction: Literal["buy", "sell"]
    lot_size: float  = Field(gt=0.0)
    stop_loss: float = Field(gt=0.0, description="Absolute SL price")
    take_profit: float = Field(gt=0.0, description="Absolute TP price")
    comment: str     = "TradingAI_V3"
    magic: int       = 234000


class OrderOpenResponse(BaseModel):
    ticket: int
    symbol: str
    direction: str
    lot_size: float
    open_price: float
    stop_loss: float
    take_profit: float
    comment: str


class OrderCloseRequest(BaseModel):
    ticket: int
    lot_size: float | None = None   # None = close full position


class OrderCloseResponse(BaseModel):
    ticket: int
    close_price: float
    profit: float
    comment: str


class MT5InitResponse(BaseModel):
    connected: bool
    account: int | None
    server: str | None
    balance: float | None
    message: str


# ── GET /health ────────────────────────────────────────────────────────────────

@app.get("/health", summary="MT5 connection health check", dependencies=[_auth])
async def health():
    """
    Always returns HTTP 200. The body carries `mt5_connected` so the watchdog
    can distinguish a reachable-but-disconnected bridge from an unreachable host
    (the latter raises a network exception before this handler fires).
    """
    if not _mt5_connected:
        return {
            "status": "degraded",
            "mt5_connected": False,
            "is_standby": IS_STANDBY,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _account():
        with _mt5_lock:
            return mt5.account_info()

    info = await asyncio.to_thread(_account)
    return {
        "status": "ok",
        "mt5_connected": True,
        "is_standby": IS_STANDBY,
        "account": info.login if info else None,
        "server": info.server if info else None,
        "balance": info.balance if info else None,
        "equity": info.equity if info else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── GET /ohlc/{symbol}/{timeframe} ────────────────────────────────────────────

@app.get(
    "/ohlc/{symbol}/{timeframe}",
    response_model=OHLCResponse,
    summary="Fetch OHLC bars from MT5",
    dependencies=[_auth],
)
async def get_ohlc(symbol: str, timeframe: str, count: int = 500):
    """
    Returns the most recent `count` closed bars (bar 0 = current unclosed bar
    is skipped — position 1 is used as the start). Max count: 5000.

    timeframe accepts: M1 M5 M15 M30 H1 H4 D1 W1 MN1
    """
    _require_connected()

    tf = _TF_MAP.get(timeframe.upper())
    if tf is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown timeframe '{timeframe}'. Valid values: {list(_TF_MAP)}",
        )
    if not 1 <= count <= 5000:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "count must be between 1 and 5000",
        )

    def _fetch():
        with _mt5_lock:
            # position=1 skips the current unclosed bar
            return mt5.copy_rates_from_pos(symbol.upper(), tf, 1, count)

    rates = await asyncio.to_thread(_fetch)

    if rates is None or len(rates) == 0:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No OHLC data for {symbol} {timeframe} — MT5 error: {mt5.last_error()}",
        )

    return OHLCResponse(
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        count=len(rates),
        bars=[
            OHLCBar(
                time=int(r["time"]),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=int(r["tick_volume"]),
                spread=float(r["spread"]),
            )
            for r in rates
        ],
    )


# ── GET /spread/{symbol} ──────────────────────────────────────────────────────

@app.get(
    "/spread/{symbol}",
    response_model=SpreadResponse,
    summary="Get current live spread",
    dependencies=[_auth],
)
async def get_spread(symbol: str):
    """
    Returns current bid, ask, and spread in both points and pips.
    XAU/USD spread_pips equals spread_points (pip divisor = 1.0).
    """
    _require_connected()

    def _fetch():
        sym = symbol.upper()
        with _mt5_lock:
            info = mt5.symbol_info(sym)
            tick = mt5.symbol_info_tick(sym)
        return info, tick

    info, tick = await asyncio.to_thread(_fetch)

    if info is None or tick is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Symbol '{symbol}' not found in MT5 market watch",
        )

    divisor = _PIP_DIVISOR.get(symbol.upper(), 10.0)
    spread_points = float(info.spread)

    return SpreadResponse(
        symbol=symbol.upper(),
        spread_points=spread_points,
        spread_pips=round(spread_points / divisor, 2),
        bid=tick.bid,
        ask=tick.ask,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ── POST /order/open ──────────────────────────────────────────────────────────

@app.post(
    "/order/open",
    response_model=OrderOpenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open a market order",
    dependencies=[_auth],
)
async def order_open(body: OrderOpenRequest):
    """
    Sends a market BUY or SELL order via mt5.order_send(). SL and TP are
    absolute prices calculated by the signal_generator before this call.

    Returns the broker-assigned ticket on success, or HTTP 400 with the
    MT5 retcode description on rejection.
    """
    _require_connected()

    order_type = mt5.ORDER_TYPE_BUY if body.direction == "buy" else mt5.ORDER_TYPE_SELL

    def _send():
        sym = body.symbol.upper()
        with _mt5_lock:
            tick = mt5.symbol_info_tick(sym)
            if tick is None:
                return None, f"Symbol '{sym}' not found in MT5 market watch"
            price = tick.ask if body.direction == "buy" else tick.bid
            result = mt5.order_send({
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       sym,
                "volume":       float(body.lot_size),
                "type":         order_type,
                "price":        price,
                "sl":           float(body.stop_loss),
                "tp":           float(body.take_profit),
                "deviation":    20,
                "magic":        body.magic,
                "comment":      body.comment,
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            })
        return result, None

    result, err = await asyncio.to_thread(_send)

    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, err)

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Order rejected: retcode={result.retcode} comment='{result.comment}'",
        )

    return OrderOpenResponse(
        ticket=result.order,
        symbol=body.symbol.upper(),
        direction=body.direction,
        lot_size=body.lot_size,
        open_price=result.price,
        stop_loss=body.stop_loss,
        take_profit=body.take_profit,
        comment=body.comment,
    )


# ── POST /order/close ─────────────────────────────────────────────────────────

@app.post(
    "/order/close",
    response_model=OrderCloseResponse,
    summary="Close an open position by ticket",
    dependencies=[_auth],
)
async def order_close(body: OrderCloseRequest):
    """
    Closes an open position. Pass lot_size for a partial close; omit (null)
    to close the full position. Sends a counter-direction market order.
    """
    _require_connected()

    def _close():
        with _mt5_lock:
            positions = mt5.positions_get(ticket=body.ticket)
            if not positions:
                return None, f"No open position for ticket {body.ticket}"

            pos = positions[0]
            close_type = (
                mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY
                else mt5.ORDER_TYPE_BUY
            )
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                return None, f"Symbol '{pos.symbol}' not found"

            close_price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
            volume = float(body.lot_size) if body.lot_size is not None else pos.volume

            result = mt5.order_send({
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       pos.symbol,
                "volume":       volume,
                "type":         close_type,
                "position":     body.ticket,
                "price":        close_price,
                "deviation":    20,
                "magic":        pos.magic,
                "comment":      "TradingAI_V3_close",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            })
        return result, None

    result, err = await asyncio.to_thread(_close)

    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, err)

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Close rejected: retcode={result.retcode} comment='{result.comment}'",
        )

    return OrderCloseResponse(
        ticket=body.ticket,
        close_price=result.price,
        profit=result.profit,
        comment=result.comment,
    )


# ── POST /mt5/initialize ──────────────────────────────────────────────────────

@app.post(
    "/mt5/initialize",
    response_model=MT5InitResponse,
    summary="(Re-)initialize the MT5 terminal connection",
    dependencies=[_auth],
)
async def mt5_initialize():
    """
    Called by bridge_watchdog.py after promoting this standby to primary.
    Shuts down any existing connection first, then reconnects using env-var
    credentials. Safe to call on a connected instance (idempotent restart).
    """
    await asyncio.to_thread(_mt5_shutdown)
    ok = await asyncio.to_thread(_mt5_init)

    if not ok:
        return MT5InitResponse(
            connected=False,
            account=None,
            server=None,
            balance=None,
            message=f"MT5 init failed — {mt5.last_error()}",
        )

    def _info():
        with _mt5_lock:
            return mt5.account_info()

    info = await asyncio.to_thread(_info)
    return MT5InitResponse(
        connected=True,
        account=info.login if info else None,
        server=info.server if info else None,
        balance=info.balance if info else None,
        message="MT5 connected successfully",
    )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("MT5_BRIDGE_PORT", "8001"))
    uvicorn.run(
        "core.execution_engine.mt5_bridge:app",
        host="0.0.0.0",
        port=port,
        workers=1,          # must be 1 — single MT5 terminal per process
        log_level="info",
    )
