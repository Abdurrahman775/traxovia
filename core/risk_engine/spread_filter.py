"""
core/risk_engine/spread_filter.py — Gate 6 spread check.

Fetches the live spread directly from MT5 and blocks the signal if the
current spread exceeds 1.5× the symbol's normal baseline.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False

SPREAD_BASELINES: dict[str, float] = {
    "EURUSD": 1.0,
    "GBPUSD": 1.2,
    "USDJPY": 1.0,
    "AUDUSD": 1.2,
    "XAUUSD": 25.0,
}

SPREAD_MULTIPLIER = 1.5
_PIP_MULT: dict[str, float] = {"JPY": 100.0, "XAU": 10.0, "GOLD": 10.0}


def _pip_multiplier(symbol: str) -> float:
    for key, mult in _PIP_MULT.items():
        if key in symbol:
            return mult
    return 10_000.0


def _get_spread_pips_sync(symbol: str) -> float | None:
    if not _MT5_AVAILABLE or not mt5.initialize():
        return None
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    spread_points = tick.ask - tick.bid
    return round(spread_points * _pip_multiplier(symbol), 2)


async def check_spread(symbol: str) -> dict:
    sym      = symbol.upper()
    baseline = SPREAD_BASELINES.get(sym)

    if baseline is None:
        return _result(
            allowed=False, symbol=sym, current_spread=None, baseline=0.0, threshold=0.0,
            reason=f"No spread baseline configured for '{sym}' — signal blocked",
        )

    threshold = round(baseline * SPREAD_MULTIPLIER, 2)

    if not _MT5_AVAILABLE:
        return _result(
            allowed=False, symbol=sym, current_spread=None, baseline=baseline, threshold=threshold,
            reason="MT5 not available on this platform — deploy on Windows VPS",
        )

    current_pips = await asyncio.to_thread(_get_spread_pips_sync, sym)

    if current_pips is None:
        return _result(
            allowed=False, symbol=sym, current_spread=None, baseline=baseline, threshold=threshold,
            reason="MT5 not initialized or tick unavailable — signal blocked",
        )

    if current_pips > threshold:
        logger.info(
            "spread_filter: %s BLOCKED — spread=%.2f pips > threshold=%.2f",
            sym, current_pips, threshold,
        )
        return _result(
            allowed=False, symbol=sym, current_spread=current_pips,
            baseline=baseline, threshold=threshold,
            reason=(
                f"Spread too wide: {current_pips:.2f} pips > "
                f"threshold {threshold:.2f} pips ({baseline:.2f} × {SPREAD_MULTIPLIER})"
            ),
        )

    return _result(
        allowed=True, symbol=sym, current_spread=current_pips,
        baseline=baseline, threshold=threshold,
        reason=f"Spread {current_pips:.2f} pips within threshold {threshold:.2f} pips",
    )


def _result(*, allowed, symbol, current_spread, baseline, threshold, reason) -> dict:
    return {
        "allowed":        allowed,
        "symbol":         symbol,
        "current_spread": current_spread,
        "baseline":       baseline,
        "threshold":      threshold,
        "reason":         reason,
    }
