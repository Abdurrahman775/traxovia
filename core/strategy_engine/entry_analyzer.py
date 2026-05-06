"""core/strategy_engine/entry_analyzer.py — M15 entry confirmation gate."""
from __future__ import annotations

import pandas as pd


class EntryAnalyzer:
    """Confirm entry trigger and compute SL/TP pip values."""

    def check_gate(
        self,
        df: pd.DataFrame,
        bias: dict | None = None,
        zone: dict | None = None,
    ) -> dict:
        return {"passed": False, "reason": "no entry signal"}
