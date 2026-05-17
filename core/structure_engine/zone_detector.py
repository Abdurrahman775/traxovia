"""core/structure_engine/zone_detector.py — Supply/demand zone detection."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Zone:
    zone_type:    str
    top:          float
    bottom:       float
    strength:     float
    test_count:   int
    origin_index: int
    created_at:   pd.Timestamp


class ZoneDetector:
    """Detect supply/demand zones from M15 OHLC and gate whether price is near one."""

    _IMPULSE_MULT   = 1.8    # impulse body must be ≥ 1.8× recent avg body
    _ZONE_TOLERANCE = 0.003  # 0.3% of price = "at the zone"
    _NEAR_MULT      = 3.0    # approaching within 3× tolerance also qualifies
    _MAX_TEST_COUNT = 3      # zones tested more than this are invalid
    _LOOKBACK       = 150    # bars back to scan

    def check_gate(self, df: pd.DataFrame, direction: str | None = None) -> dict:
        if direction is None:
            return {"passed": False, "zone": None, "reason": "no_direction"}
        if df is None or len(df) < 20:
            return {"passed": False, "zone": None, "reason": "insufficient_data"}

        zones       = self._detect_zones(df)
        target_type = "demand" if direction == "bullish" else "supply"
        candidates  = [z for z in zones if z.zone_type == target_type
                       and z.test_count < self._MAX_TEST_COUNT]

        if not candidates:
            return {"passed": False, "zone": None, "reason": f"no_{target_type}_zone"}

        price = float(df["close"].iloc[-1])
        best  = self._nearest_valid_zone(candidates, price, direction)

        if best is None:
            return {"passed": False, "zone": None,
                    "reason": f"price_not_near_{target_type}_zone"}

        return {"passed": True, "zone": best, "reason": f"at_{target_type}_zone"}

    # ── Detection ──────────────────────────────────────────────────────────────

    def _detect_zones(self, df: pd.DataFrame) -> list[Zone]:
        zones: list[Zone] = []

        closes = df["close"].values.astype(float)
        opens  = df["open"].values.astype(float)
        highs  = df["high"].values.astype(float)
        lows   = df["low"].values.astype(float)
        bodies = np.abs(closes - opens)

        # Search from `start` up to but not including the current (last) bar
        start = max(1, len(df) - self._LOOKBACK - 1)
        end   = len(df) - 1

        for i in range(start, end):
            avg_body = bodies[max(0, i - 20):i].mean() if i >= 2 else (bodies[0] or 1e-8)
            if avg_body < 1e-8:
                continue

            impulse_body = bodies[i]
            if impulse_body < self._IMPULSE_MULT * avg_body:
                continue

            # The "base" candle is the bar just before the impulse
            base = i - 1
            if base < 0:
                continue

            z_top    = max(opens[base], closes[base])
            z_bottom = min(opens[base], closes[base])

            # If the body is very small, use the full candle range instead
            if (z_top - z_bottom) < (highs[base] - lows[base]) * 0.25:
                z_top    = highs[base]
                z_bottom = lows[base]

            zone_type = "demand" if closes[i] > opens[i] else "supply"
            strength  = min(1.0, impulse_body / (avg_body * self._IMPULSE_MULT))
            ts = (df.index[base] if isinstance(df.index[base], pd.Timestamp)
                  else pd.Timestamp.now())

            zones.append(Zone(
                zone_type=zone_type,
                top=round(float(z_top), 6),
                bottom=round(float(z_bottom), 6),
                strength=round(strength, 3),
                test_count=0,
                origin_index=base,
                created_at=ts,
            ))

        return zones

    # ── Zone proximity check ───────────────────────────────────────────────────

    def _nearest_valid_zone(
        self, zones: list[Zone], price: float, direction: str,
    ) -> Zone | None:
        tol      = price * self._ZONE_TOLERANCE
        wide_tol = tol * self._NEAR_MULT

        in_zone: list[Zone]   = []
        near_zone: list[Zone] = []

        for z in zones:
            if z.bottom - tol <= price <= z.top + tol:
                in_zone.append(z)
            elif direction == "bullish" and z.top < price <= z.top + wide_tol:
                # Price just pulled back to the top edge of a demand zone
                near_zone.append(z)
            elif direction == "bearish" and z.bottom - wide_tol <= price < z.bottom:
                # Price just pulled back to the bottom edge of a supply zone
                near_zone.append(z)

        pool = in_zone or near_zone
        if not pool:
            return None

        # Prefer the freshest (most recently formed) zone
        return max(pool, key=lambda z: z.origin_index)
