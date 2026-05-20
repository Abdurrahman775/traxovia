"""core/structure_engine/order_block_detector.py — ICT Order Block detection.

Phase 2 of the ICT migration. Replaces the supply/demand ZoneDetector with
precise Order Block identification.

WHAT IS AN ORDER BLOCK:
  Bullish OB:  The last bearish (red) candle immediately before a strong bullish
               impulse move. Represents the last price level where institutions
               were selling before reversing to buy aggressively.
  Bearish OB:  The last bullish (green) candle immediately before a strong bearish
               impulse move. Last level where institutions were buying before
               reversing to sell aggressively.

WHY OBs BEAT SUPPLY/DEMAND ZONES:
  - Supply/demand zones are broad areas; OBs are single precise candles
  - OBs mark the exact candle where institutions flipped — much tighter SL
  - Price returns to OBs to fill institutional orders (mitigates the OB)
  - Unmitigated OBs (price hasn't returned yet) = highest probability entries

ENTRY LOGIC:
  Price retraces INTO the OB body (between OB open and close) after the impulse.
  SL goes beyond the OB wick. TP targets the next liquidity pool (3R).

Returns the same interface as ZoneDetector.check_gate() so nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.structure_engine.zone_detector import Zone


_IMPULSE_MULT  = 3.0   # impulse move must be ≥ 3× the OB candle's body
_IMPULSE_BARS  = 6     # bars after OB candle to confirm the impulse
_MAX_OB_AGE    = 80    # M15 bars (~20 hours) — unmitigated OBs only
_OB_TOLERANCE  = 0.002 # 0.2% price tolerance for "inside OB" check
_MIN_OB_BODY   = 0.3   # OB candle body must be ≥ 30% of its full range


def _avg_body(candles: pd.DataFrame) -> float:
    bodies = abs(candles["close"].values - candles["open"].values).astype(float)
    return float(bodies.mean()) if len(bodies) > 0 else 0.0


class OrderBlockDetector:
    """ICT Order Block detector — drop-in replacement for ZoneDetector."""

    def check_gate(self, df: pd.DataFrame, direction: str | None = None) -> dict:
        """
        Detect the most recent unmitigated Order Block and check if price is inside it.

        Returns same interface as ZoneDetector.check_gate():
            {"passed": bool, "zone": Zone | None, "reason": str}
        """
        if direction is None:
            return {"passed": False, "zone": None, "reason": "no_direction"}
        if df is None or len(df) < 30:
            return {"passed": False, "zone": None, "reason": "insufficient_data"}

        ob = self._find_order_block(df, direction)
        if ob is None:
            return {"passed": False, "zone": None,
                    "reason": f"no_{'bullish' if direction == 'bullish' else 'bearish'}_order_block"}

        # Check price is inside or approaching the OB
        price     = float(df["close"].iloc[-1])
        ob_top    = ob.top
        ob_bottom = ob.bottom
        tolerance = (ob_top - ob_bottom) * _OB_TOLERANCE + ob_bottom * _OB_TOLERANCE

        inside_ob     = ob_bottom - tolerance <= price <= ob_top + tolerance
        approaching   = (direction == "bullish" and price <= ob_top + tolerance * 3) or \
                        (direction == "bearish" and price >= ob_bottom - tolerance * 3)

        if not (inside_ob or approaching):
            return {"passed": False, "zone": None,
                    "reason": f"price_not_at_ob_{price:.5f}_ob=[{ob_bottom:.5f},{ob_top:.5f}]"}

        return {"passed": True, "zone": ob,
                "reason": f"price_at_{'bullish' if direction == 'bullish' else 'bearish'}_ob"}

    def _find_order_block(self, df: pd.DataFrame, direction: str) -> Zone | None:
        """Find the most recent unmitigated Order Block for the given direction."""
        opens  = df["open"].values.astype(float)
        highs  = df["high"].values.astype(float)
        lows   = df["low"].values.astype(float)
        closes = df["close"].values.astype(float)
        n      = len(df)

        avg_b  = _avg_body(df.iloc[-50:] if n >= 50 else df)
        if avg_b == 0:
            return None

        last_idx = n - 1
        best_ob: Zone | None = None

        # Scan backwards — most recent unmitigated OB wins
        scan_start = max(0, n - _MAX_OB_AGE - _IMPULSE_BARS)

        for i in range(n - _IMPULSE_BARS - 1, scan_start, -1):
            ob_open  = opens[i]
            ob_close = closes[i]
            ob_high  = highs[i]
            ob_low   = lows[i]
            ob_body  = abs(ob_close - ob_open)
            ob_range = ob_high - ob_low

            if ob_range == 0:
                continue

            # OB candle must have a meaningful body
            if ob_body / ob_range < _MIN_OB_BODY:
                continue

            if direction == "bullish":
                # Bullish OB = last bearish candle before bullish impulse
                if ob_close >= ob_open:  # not bearish
                    continue

                # Confirm bullish impulse in next _IMPULSE_BARS candles
                impulse_high = max(highs[i + 1 : i + _IMPULSE_BARS + 1])
                impulse_move = impulse_high - ob_high
                if impulse_move < avg_b * _IMPULSE_MULT:
                    continue

                # OB must be unmitigated: price never closed below OB low after impulse
                post_lows = lows[i + 1 : last_idx + 1]
                if len(post_lows) > 0 and min(post_lows) < ob_low:
                    continue  # OB was mitigated (price wicked through)

                ob_top    = max(ob_open, ob_close)  # top of OB body
                ob_bottom = min(ob_open, ob_close)  # bottom of OB body
                age       = last_idx - i
                strength  = min(1.0, impulse_move / (avg_b * _IMPULSE_MULT * 2))

                best_ob = Zone(
                    zone_type    = "demand",
                    top          = round(ob_top, 6),
                    bottom       = round(ob_bottom, 6),
                    strength     = round(strength, 4),
                    test_count   = 0,
                    origin_index = i,
                    created_at   = pd.Timestamp.now(),
                )
                break  # most recent valid OB found

            else:  # bearish
                # Bearish OB = last bullish candle before bearish impulse
                if ob_close <= ob_open:  # not bullish
                    continue

                # Confirm bearish impulse in next _IMPULSE_BARS candles
                impulse_low  = min(lows[i + 1 : i + _IMPULSE_BARS + 1])
                impulse_move = ob_low - impulse_low
                if impulse_move < avg_b * _IMPULSE_MULT:
                    continue

                # OB must be unmitigated: price never closed above OB high after impulse
                post_highs = highs[i + 1 : last_idx + 1]
                if len(post_highs) > 0 and max(post_highs) > ob_high:
                    continue  # OB was mitigated

                ob_top    = max(ob_open, ob_close)
                ob_bottom = min(ob_open, ob_close)
                strength  = min(1.0, impulse_move / (avg_b * _IMPULSE_MULT * 2))

                best_ob = Zone(
                    zone_type    = "supply",
                    top          = round(ob_top, 6),
                    bottom       = round(ob_bottom, 6),
                    strength     = round(strength, 4),
                    test_count   = 0,
                    origin_index = i,
                    created_at   = pd.Timestamp.now(),
                )
                break

        return best_ob
