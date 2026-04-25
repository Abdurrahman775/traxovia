"""
core/risk_engine/spread_filter.py — Gate 6 spread check.

Fetches the live spread from the active MT5 bridge and blocks the signal if
the current spread exceeds 1.5× the symbol's normal baseline. Wide spreads
occur around major news releases and market opens — trading through them
erodes R/R significantly and is a known V2 failure mode.

Usage (inside signal_generator.py):
    from core.risk_engine.spread_filter import check_spread

    result = await check_spread("EURUSD")
    if not result["allowed"]:
        return {"gate": "risk_filter", "reason": result["reason"]}
"""

import logging
import os

import httpx

from core.execution_engine.bridge_watchdog import bridge_state

logger = logging.getLogger(__name__)

# ── Per-symbol normal spread baselines (pips) ──────────────────────────────────
# Sourced from Exness typical spreads on a Standard account during liquid hours.
# XAU/USD baseline is in the same unit returned by /spread/{symbol} (points = pips
# for gold at Exness 2-decimal quoting).

SPREAD_BASELINES: dict[str, float] = {
    "EURUSD": 1.0,
    "GBPUSD": 1.2,
    "USDJPY": 1.0,
    "AUDUSD": 1.2,
    "XAUUSD": 25.0,
}

SPREAD_MULTIPLIER = 1.5   # block if current > baseline × this

_API_KEY = os.getenv("MT5_BRIDGE_API_KEY", "")
_TIMEOUT = 5.0            # seconds — fail fast; a slow bridge is itself a risk signal


# ── Public interface ───────────────────────────────────────────────────────────

async def check_spread(symbol: str) -> dict:
    """
    Check whether the current live spread for *symbol* is within the acceptable
    threshold for signal generation.

    Returns a dict:
        {
            "allowed":        bool,
            "symbol":         str,
            "current_spread": float | None,   # pips; None if bridge unreachable
            "baseline":       float,
            "threshold":      float,          # baseline × 1.5
            "reason":         str,            # human-readable gate result
        }

    Blocks (allowed=False) when:
      - bridge is unreachable or returns an error (fail-safe: block on uncertainty)
      - current spread_pips > baseline × 1.5
    """
    sym = symbol.upper()
    baseline  = SPREAD_BASELINES.get(sym)
    threshold = round(baseline * SPREAD_MULTIPLIER, 2) if baseline is not None else None

    if baseline is None:
        return _result(
            allowed=False,
            symbol=sym,
            current_spread=None,
            baseline=0.0,
            threshold=0.0,
            reason=f"No spread baseline configured for '{sym}' — signal blocked",
        )

    active_url = bridge_state.get("active_url") or ""
    if not active_url:
        return _result(
            allowed=False,
            symbol=sym,
            current_spread=None,
            baseline=baseline,
            threshold=threshold,
            reason="No active bridge URL in bridge_state — signal blocked",
        )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{active_url}/spread/{sym}",
                headers={"X-Api-Key": _API_KEY},
            )
        resp.raise_for_status()
        data = resp.json()
        current_pips = float(data["spread_pips"])

    except httpx.TimeoutException:
        logger.warning("spread_filter: timeout reaching bridge for %s", sym)
        return _result(
            allowed=False,
            symbol=sym,
            current_spread=None,
            baseline=baseline,
            threshold=threshold,
            reason=f"Bridge timeout after {_TIMEOUT}s — spread unverifiable, signal blocked",
        )
    except httpx.HTTPStatusError as exc:
        logger.warning("spread_filter: bridge returned %s for %s", exc.response.status_code, sym)
        return _result(
            allowed=False,
            symbol=sym,
            current_spread=None,
            baseline=baseline,
            threshold=threshold,
            reason=f"Bridge HTTP {exc.response.status_code} — spread unverifiable, signal blocked",
        )
    except Exception as exc:
        logger.warning("spread_filter: unexpected error for %s — %s", sym, exc)
        return _result(
            allowed=False,
            symbol=sym,
            current_spread=None,
            baseline=baseline,
            threshold=threshold,
            reason=f"Bridge unreachable ({exc.__class__.__name__}) — signal blocked",
        )

    if current_pips > threshold:
        logger.info(
            "spread_filter: %s BLOCKED — spread=%.2f pips > threshold=%.2f (baseline=%.2f × %.1f)",
            sym, current_pips, threshold, baseline, SPREAD_MULTIPLIER,
        )
        return _result(
            allowed=False,
            symbol=sym,
            current_spread=current_pips,
            baseline=baseline,
            threshold=threshold,
            reason=(
                f"Spread too wide: {current_pips:.2f} pips > "
                f"threshold {threshold:.2f} pips ({baseline:.2f} × {SPREAD_MULTIPLIER})"
            ),
        )

    logger.debug("spread_filter: %s OK — spread=%.2f pips (threshold=%.2f)", sym, current_pips, threshold)
    return _result(
        allowed=True,
        symbol=sym,
        current_spread=current_pips,
        baseline=baseline,
        threshold=threshold,
        reason=f"Spread {current_pips:.2f} pips within threshold {threshold:.2f} pips",
    )


# ── Helper ─────────────────────────────────────────────────────────────────────

def _result(
    *,
    allowed: bool,
    symbol: str,
    current_spread: float | None,
    baseline: float,
    threshold: float,
    reason: str,
) -> dict:
    return {
        "allowed":        allowed,
        "symbol":         symbol,
        "current_spread": current_spread,
        "baseline":       baseline,
        "threshold":      threshold,
        "reason":         reason,
    }
