"""core/structure_engine/zone_detector.py — Supply/demand zone detection."""
from __future__ import annotations

from dataclasses import dataclass

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
    """Detect supply/demand zones and gate whether price is near one."""

    def check_gate(self, df: pd.DataFrame, direction: str | None = None) -> dict:
        return {"passed": False, "zone": None, "reason": "no zone detected"}
