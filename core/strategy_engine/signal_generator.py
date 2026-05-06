"""core/strategy_engine/signal_generator.py — 7-gate signal pipeline."""
from __future__ import annotations

import pandas as pd

from core.risk_engine.drawdown_monitor import evaluate_drawdown
from core.risk_engine.position_sizer import calculate_lot_size
from core.risk_engine.spread_filter import check_spread as check_risk_gate  # noqa: F401
from core.strategy_engine.bias_analyzer import BiasAnalyzer
from core.strategy_engine.entry_analyzer import EntryAnalyzer
from core.structure_engine.regime_classifier import RegimeClassifier
from core.structure_engine.zone_detector import ZoneDetector

# Module-level instances — tests patch these by dotted path
_regime_clf = RegimeClassifier()
_bias_anl   = BiasAnalyzer()
_zone_det   = ZoneDetector()
_entry_anl  = EntryAnalyzer()


async def generate_signal(
    symbol: str,
    htf_df: pd.DataFrame,
    m15_df: pd.DataFrame,
    user_id: str,
    db,
    account_balance: float = 10_000.0,
    risk_pct: float = 0.01,
) -> dict:
    """Run the 7-gate signal pipeline and return a result dict."""
    now = pd.Timestamp.now()

    def _blocked(gate: int, reason: str) -> dict:
        return {
            "signal":    None,
            "gate":      gate,
            "reason":    reason,
            "symbol":    symbol,
            "user_id":   user_id,
            "timestamp": now,
        }

    # Gate 1 — Regime
    regime_result = _regime_clf.classify(htf_df)
    if regime_result["signal_gate"] == "blocked":
        return _blocked(1, "regime_blocked")

    # Gate 2 — HTF Bias
    bias_result = _bias_anl.analyze(htf_df, symbol)
    if not bias_result.get("direction"):
        return _blocked(2, "no_htf_bias")

    # Gate 3 — Supply/Demand Zone
    zone_result = _zone_det.check_gate(m15_df, bias_result["direction"])
    if not zone_result.get("passed"):
        return _blocked(3, "no_zone")

    # Gate 4 — Entry confirmation
    entry_result = _entry_anl.check_gate(m15_df, bias_result, zone_result)
    if not entry_result.get("passed"):
        return _blocked(4, "no_entry")

    # Gate 5 — Spread / risk check  (check_risk_gate is patched in tests)
    risk_result = await check_risk_gate(symbol)
    if not risk_result.get("allowed"):
        return _blocked(5, "risk_blocked")

    # Gate 6 — Lot size sanity (internal; no external call needed)
    lot = calculate_lot_size(
        account_balance=account_balance,
        risk_pct=risk_pct,
        sl_pips=entry_result["sl_pips"],
        symbol=symbol,
        regime=regime_result["regime"],
        dd_stage=0,
    )
    if lot <= 0:
        return _blocked(6, "lot_zero")

    # Gate 7 — Drawdown protocol
    dd_result = await evaluate_drawdown(user_id, db)
    if not dd_result["trading_allowed"]:
        return _blocked(7, "dd_paused")

    # Recalculate lot with confirmed DD stage
    lot = calculate_lot_size(
        account_balance=account_balance,
        risk_pct=risk_pct,
        sl_pips=entry_result["sl_pips"],
        symbol=symbol,
        regime=regime_result["regime"],
        dd_stage=dd_result["stage"],
    )

    return {
        "signal":        "generated",
        "gate":          7,
        "reason":        "signal_generated",
        "symbol":        symbol,
        "user_id":       user_id,
        "timestamp":     now,
        "direction":     bias_result["direction"],
        "entry_price":   entry_result["entry_price"],
        "sl_price":      entry_result["sl_price"],
        "tp_price":      entry_result["tp_price"],
        "sl_pips":       entry_result["sl_pips"],
        "tp_pips":       entry_result["tp_pips"],
        "lot_size":      lot,
        "regime":        regime_result["regime"],
        "adx":           regime_result["adx"],
        "bias_strength": bias_result["strength"],
        "zone_strength": zone_result["zone"].strength,
    }
