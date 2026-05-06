"""core/risk_engine/position_sizer.py — Lot size calculator with DD stage caps."""
from __future__ import annotations

from core.risk_engine.drawdown_monitor import _STAGE_CFG

_STAGE_RISK_CAP: dict[int, float] = {
    0: 0.02,
    1: 0.005,
    2: 0.0025,
    3: 0.0,
}


def _pip_value_per_lot(symbol: str) -> float:
    if "JPY" in symbol: return 1000.0
    if "XAU" in symbol: return 100.0
    return 10.0


def calculate_lot_size(
    account_balance: float,
    risk_pct: float,
    sl_pips: float,
    symbol: str = "EURUSD",
    regime: str = "trending",
    dd_stage: int = 0,
) -> float:
    if dd_stage == 3 or sl_pips == 0:
        return 0.0
    adjusted_risk  = risk_pct * (0.5 if regime == "volatile" else 1.0)
    cap            = _STAGE_RISK_CAP[dd_stage]
    effective_risk = min(adjusted_risk, cap)
    risk_amount    = account_balance * effective_risk
    pip_val     = _pip_value_per_lot(symbol)
    lot         = risk_amount / (sl_pips * pip_val)
    return max(0.01, round(lot, 2))
