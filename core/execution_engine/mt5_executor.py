"""core/execution_engine/mt5_executor.py — MT5 trade execution.

On Linux with Wine bridge: MetaTrader5 package is not installed natively, but
mt5_bridge.client provides the same interface via HTTP to the Wine-hosted server.

On Linux without the bridge (dev / CI): _MT5_AVAILABLE = False; all functions
raise BridgeError with a clear message so the stack still imports cleanly.
"""
from __future__ import annotations
from dataclasses import dataclass

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    try:
        from mt5_bridge import client as mt5
        _MT5_AVAILABLE = True
    except Exception:
        _MT5_AVAILABLE = False


class BridgeError(Exception):
    pass

# Legacy alias kept for existing callers
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

# Legacy alias
OrderResult = OrderOpenResult


@dataclass
class OrderCloseResult:
    ticket:      int
    close_price: float
    profit:      float
    comment:     str

# Legacy alias
CloseResult = OrderCloseResult


def _require_mt5() -> None:
    if not _MT5_AVAILABLE:
        raise BridgeError(
            "MT5 not available. Start mt5-bridge.service (see scripts/setup_wine_mt5.sh)."
        )
    if not mt5.initialize():
        raise BridgeError(f"MT5 initialize() failed: {mt5.last_error()}")


def _get_fill_mode(symbol: str) -> int:
    """Return the best ORDER_FILLING mode supported by this broker/symbol.

    Brokers expose a bitmask via symbol_info.filling_mode:
      bit 0 (1) = FOK, bit 1 (2) = IOC, bit 2 (4) = RETURN.
    Prefer FOK → IOC → RETURN so we always use a valid mode.
    """
    info = mt5.symbol_info(symbol)
    mode = info.filling_mode if info else 0
    if mode & 1:
        return mt5.ORDER_FILLING_FOK
    if mode & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


async def open_order(
    symbol:      str,
    direction:   str,
    lot_size:    float,
    stop_loss:   float,
    take_profit: float,
    comment:     str = "TradingAI_V3",
) -> OrderOpenResult:
    _require_mt5()

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise BridgeError(f"symbol_info_tick({symbol}) failed: {mt5.last_error()}")

    order_type = mt5.ORDER_TYPE_BUY if direction.lower() == "buy" else mt5.ORDER_TYPE_SELL
    price      = tick.ask if direction.lower() == "buy" else tick.bid

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       lot_size,
        "type":         order_type,
        "price":        price,
        "sl":           stop_loss,
        "tp":           take_profit,
        "comment":      comment,
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": _get_fill_mode(symbol),
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        code = result.retcode if result else "None"
        raise BridgeError(f"order_send failed: retcode={code}")

    return OrderOpenResult(
        ticket=result.order,
        symbol=symbol,
        direction=direction,
        lot_size=lot_size,
        open_price=result.price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        comment=comment,
    )


async def close_order(ticket: int, lot_size: float | None = None) -> OrderCloseResult:
    _require_mt5()

    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        raise BridgeError(f"Position {ticket} not found: {mt5.last_error()}")

    pos    = positions[0]
    volume = lot_size if lot_size is not None else pos.volume

    # Close BUY with SELL, close SELL with BUY
    close_type  = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
    tick        = mt5.symbol_info_tick(pos.symbol)
    close_price = tick.bid if pos.type == 0 else tick.ask

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       pos.symbol,
        "volume":       volume,
        "type":         close_type,
        "position":     ticket,
        "price":        close_price,
        "comment":      "close",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": _get_fill_mode(pos.symbol),
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        code = result.retcode if result else "None"
        raise BridgeError(f"close order_send failed: retcode={code}")

    return OrderCloseResult(
        ticket=ticket,
        close_price=result.price,
        profit=pos.profit,
        comment="closed",
    )
