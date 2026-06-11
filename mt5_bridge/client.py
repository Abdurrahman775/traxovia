"""mt5_bridge/client.py — Linux-side HTTP proxy for MetaTrader5.

Provides the same interface as the MetaTrader5 Python package (constants,
functions, return-object attributes) but routes every call via HTTP to the
bridge server running inside Wine on localhost:8001.

Usage in callers — drop-in replacement for `import MetaTrader5 as mt5`:

    try:
        import MetaTrader5 as mt5
        _MT5_AVAILABLE = True
    except ImportError:
        try:
            from mt5_bridge import client as mt5
            _MT5_AVAILABLE = True
        except Exception:
            _MT5_AVAILABLE = False

The MT5_BRIDGE_URL env var overrides the default (http://127.0.0.1:8001).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

_BASE    = os.getenv("MT5_BRIDGE_URL", "http://127.0.0.1:8001")
_TIMEOUT = 15   # seconds; order sends need a little more headroom

# ── MT5 constants (matching the native package's integer values) ───────────────

TIMEFRAME_M1  = "M1"
TIMEFRAME_M5  = "M5"
TIMEFRAME_M15 = "M15"
TIMEFRAME_M30 = "M30"
TIMEFRAME_H1  = "H1"
TIMEFRAME_H4  = "H4"
TIMEFRAME_D1  = "D1"
TIMEFRAME_W1  = "W1"
TIMEFRAME_MN1 = "MN1"

ORDER_TYPE_BUY  = 0
ORDER_TYPE_SELL = 1

TRADE_ACTION_DEAL = "TRADE_ACTION_DEAL"
TRADE_ACTION_SLTP = "TRADE_ACTION_SLTP"

ORDER_FILLING_FOK    = "ORDER_FILLING_FOK"
ORDER_FILLING_IOC    = "ORDER_FILLING_IOC"
ORDER_FILLING_RETURN = "ORDER_FILLING_RETURN"

ORDER_TIME_GTC = "ORDER_TIME_GTC"

TRADE_RETCODE_DONE      = 10009
ACCOUNT_TRADE_MODE_REAL = 0

# ── Return-object shims (match MT5 namedtuple attribute names) ─────────────────

class _AccountInfo:
    __slots__ = ("login", "balance", "equity", "margin", "currency",
                 "trade_mode", "leverage", "company", "server")
    def __init__(self, d: dict):
        self.login      = d.get("login")
        self.balance    = float(d.get("balance", 0))
        self.equity     = float(d.get("equity",  0))
        self.margin     = float(d.get("margin",  0))
        self.currency   = d.get("currency",   "USD")
        self.trade_mode = int(d.get("trade_mode", 0))
        self.leverage   = int(d.get("leverage", 100))
        self.company    = d.get("company", "")
        self.server     = d.get("server",  "")


class _SymbolInfo:
    __slots__ = ("filling_mode", "spread", "digits")
    def __init__(self, d: dict):
        self.filling_mode = int(d.get("filling_mode", 1))
        self.spread       = int(d.get("spread",       0))
        self.digits       = int(d.get("digits",       5))


class _Tick:
    __slots__ = ("ask", "bid", "last", "time")
    def __init__(self, d: dict):
        self.ask  = float(d.get("ask",  0))
        self.bid  = float(d.get("bid",  0))
        self.last = float(d.get("last", 0))
        self.time = int(d.get("time",   0))


class _Position:
    __slots__ = ("ticket", "symbol", "type", "volume", "price_open", "sl", "tp", "profit")
    def __init__(self, d: dict):
        self.ticket     = d.get("ticket")
        self.symbol     = d.get("symbol")
        self.type       = int(d.get("type",       0))
        self.volume     = float(d.get("volume",    0))
        self.price_open = float(d.get("price_open",0))
        self.sl         = float(d.get("sl",        0))
        self.tp         = float(d.get("tp",        0))
        self.profit     = float(d.get("profit",    0))


class _OrderResult:
    __slots__ = ("retcode", "order", "price", "volume", "comment")
    def __init__(self, d: dict):
        self.retcode = int(d.get("retcode", -1))
        self.order   = d.get("order",   0)
        self.price   = float(d.get("price",  0))
        self.volume  = float(d.get("volume", 0))
        self.comment = d.get("comment", "")


class _Deal:
    __slots__ = ("ticket", "position_id", "entry", "price", "volume", "symbol")
    def __init__(self, d: dict):
        self.ticket      = d.get("ticket")
        self.position_id = d.get("position_id")
        self.entry       = int(d.get("entry",  0))
        self.price       = float(d.get("price", 0))
        self.volume      = float(d.get("volume",0))
        self.symbol      = d.get("symbol")


# ── Internal HTTP helpers ──────────────────────────────────────────────────────

_last_err: tuple = (0, "")


def _get(path: str, **params) -> Any:
    r = requests.get(f"{_BASE}{path}", params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict) -> Any:
    r = requests.post(f"{_BASE}{path}", json=body, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


# ── Public API — matches MetaTrader5 package interface ────────────────────────

def initialize(login: int = 0, password: str = "", server: str = "") -> bool:
    global _last_err
    try:
        body = {}
        if login and password and server:
            body = {"login": login, "password": password, "server": server}
        result = _post("/initialize", body)
        if not result.get("ok"):
            _last_err = (-1, result.get("error", "initialize failed"))
        return bool(result.get("ok"))
    except Exception as exc:
        _last_err = (-1, str(exc))
        logger.error("mt5_bridge initialize: %s", exc)
        return False


def shutdown() -> None:
    pass  # Bridge server stays running between calls


def last_error() -> tuple:
    return _last_err


def account_info() -> _AccountInfo | None:
    try:
        return _AccountInfo(_get("/account"))
    except Exception as exc:
        logger.error("mt5_bridge account_info: %s", exc)
        return None


def symbol_info(symbol: str) -> _SymbolInfo | None:
    try:
        return _SymbolInfo(_get(f"/symbol_info/{symbol}"))
    except Exception as exc:
        logger.error("mt5_bridge symbol_info %s: %s", symbol, exc)
        return None


def symbol_info_tick(symbol: str) -> _Tick | None:
    try:
        return _Tick(_get(f"/tick/{symbol}"))
    except Exception as exc:
        logger.error("mt5_bridge symbol_info_tick %s: %s", symbol, exc)
        return None


def symbol_select(symbol: str, enable: bool = True) -> bool:
    try:
        return bool(_post(f"/symbol_select/{symbol}", {}).get("ok"))
    except Exception as exc:
        logger.error("mt5_bridge symbol_select %s: %s", symbol, exc)
        return False


def copy_rates_from_pos(symbol: str, timeframe: str, start: int, count: int) -> list | None:
    """Returns a list of dicts with keys: time, open, high, low, close, tick_volume, spread."""
    try:
        return _get(f"/rates/{symbol}/{timeframe}", count=count)
    except Exception as exc:
        logger.error("mt5_bridge copy_rates_from_pos %s/%s: %s", symbol, timeframe, exc)
        return None


def order_send(request: dict) -> _OrderResult | None:
    try:
        return _OrderResult(_post("/order", request))
    except Exception as exc:
        logger.error("mt5_bridge order_send: %s", exc)
        return None


def positions_get(ticket: int | None = None) -> list[_Position] | None:
    try:
        params = {"ticket": ticket} if ticket is not None else {}
        return [_Position(p) for p in _get("/positions", **params)]
    except Exception as exc:
        logger.error("mt5_bridge positions_get: %s", exc)
        return None


def history_deals_get(from_date: datetime, to_date: datetime) -> list[_Deal] | None:
    try:
        data = _get(
            "/deals",
            from_ts=int(from_date.timestamp()),
            to_ts=int(to_date.timestamp()),
        )
        return [_Deal(d) for d in data]
    except Exception as exc:
        logger.error("mt5_bridge history_deals_get: %s", exc)
        return None
