"""core/strategy_engine/signal_generator.py — Multi-gate signal pipeline."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from core.risk_engine.drawdown_monitor import evaluate_drawdown
from core.risk_engine.position_sizer import calculate_lot_size
from core.risk_engine.spread_filter import check_spread as check_risk_gate  # noqa: F401
from core.strategy_engine.bias_analyzer import BiasAnalyzer
from core.strategy_engine.daily_bias_filter import check_daily_alignment
from core.strategy_engine.entry_analyzer import EntryAnalyzer
from core.strategy_engine.news_filter import check_news_window
from core.strategy_engine.session_filter import is_valid_session
from core.structure_engine.regime_classifier import RegimeClassifier
from core.structure_engine.zone_detector import ZoneDetector

# Module-level instances — tests patch these by dotted path
_regime_clf = RegimeClassifier()
_bias_anl   = BiasAnalyzer()
_zone_det   = ZoneDetector()
_entry_anl  = EntryAnalyzer()

# Correlated pair groups — never open same-direction trades simultaneously
_CORR_GROUPS: list[set[str]] = [{"EURUSD", "GBPUSD"}]


async def generate_signal(
    symbol: str,
    htf_df: pd.DataFrame,
    m15_df: pd.DataFrame,
    user_id: str,
    db,
    account_balance: float = 10_000.0,
    risk_pct: float = 0.01,
    open_trades: list[dict] | None = None,  # list of {"pair": str, "direction": str}
    daily_pnl_r: float = 0.0,              # cumulative R for today (for circuit breaker)
) -> dict:
    """Run the full signal pipeline and return a result dict."""
    now = pd.Timestamp.now()
    now_utc = datetime.now(timezone.utc)

    def _blocked(gate: int, reason: str) -> dict:
        return {
            "signal":    None,
            "gate":      gate,
            "reason":    reason,
            "symbol":    symbol,
            "user_id":   user_id,
            "timestamp": now,
        }

    # ── Gate 0a: Daily circuit breaker ────────────────────────────────────────
    if daily_pnl_r <= -3.0:
        return _blocked(0, "daily_loss_limit_hit")

    # ── Gate 0b: Max 2 concurrent open trades ─────────────────────────────────
    open_trades = open_trades or []
    if len(open_trades) >= 2:
        return _blocked(0, "max_concurrent_trades")

    # ── Gate 0c: Correlated pair filter ───────────────────────────────────────
    # Don't open EURUSD if GBPUSD is already open in same direction (and vice versa)
    for group in _CORR_GROUPS:
        if symbol in group:
            for ot in open_trades:
                if ot["pair"] in group and ot["pair"] != symbol:
                    return _blocked(0, f"correlated_pair_open_{ot['pair']}")

    # Session filter removed — was blocking profitable setups, hurting net R
    # is_valid_session kept in session_filter.py for future use

    # ── Gate 0e: News/event filter ────────────────────────────────────────────
    try:
        news = await check_news_window(symbol, now_utc)
        if not news["passed"]:
            return _blocked(0, f"news_window_{news.get('event', '')}")
    except Exception:
        pass  # calendar unavailable — allow trade

    # ── Gate 1: Regime ────────────────────────────────────────────────────────
    regime_result = _regime_clf.classify(htf_df)
    if regime_result["signal_gate"] == "blocked":
        return _blocked(1, "regime_blocked")

    # ── Gate 2: HTF Bias ──────────────────────────────────────────────────────
    bias_result = _bias_anl.analyze(htf_df, symbol)
    if not bias_result.get("direction"):
        return _blocked(2, "no_htf_bias")
    bias_result["symbol"] = symbol

    # Daily alignment gate removed — was filtering too many valid setups on EURUSD/GBPUSD
    # and hurting net R more than improving WR. Kept as utility in daily_bias_filter.py
    # for future experimentation.

    # ── Gate 3: Supply/Demand Zone ────────────────────────────────────────────
    zone_result = _zone_det.check_gate(m15_df, bias_result["direction"])
    if not zone_result.get("passed"):
        return _blocked(3, "no_zone")

    # ── Gate 4: Entry confirmation ────────────────────────────────────────────
    entry_result = _entry_anl.check_gate(m15_df, bias_result, zone_result)
    if not entry_result.get("passed"):
        return _blocked(4, "no_entry")

    # ── Gate 5: Spread / risk check ───────────────────────────────────────────
    risk_result = await check_risk_gate(symbol)
    if not risk_result.get("allowed"):
        return _blocked(5, "risk_blocked")

    # ── Gate 6: Lot size sanity ───────────────────────────────────────────────
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

    # ── Gate 7: Drawdown protocol ─────────────────────────────────────────────
    dd_result = await evaluate_drawdown(user_id, db)
    if not dd_result["trading_allowed"]:
        return _blocked(7, "dd_paused")

    lot = calculate_lot_size(
        account_balance=account_balance,
        risk_pct=risk_pct,
        sl_pips=entry_result["sl_pips"],
        symbol=symbol,
        regime=regime_result["regime"],
        dd_stage=dd_result["stage"],
    )

    return {
        "signal":          "generated",
        "gate":            7,
        "reason":          "signal_generated",
        "symbol":          symbol,
        "user_id":         user_id,
        "timestamp":       now,
        "direction":       bias_result["direction"],
        "entry_price":     entry_result["entry_price"],
        "sl_price":        entry_result["sl_price"],
        "tp_price":        entry_result["tp_price"],
        "sl_pips":         entry_result["sl_pips"],
        "tp_pips":         entry_result["tp_pips"],
        "lot_size":        lot,
        "regime":          regime_result["regime"],
        "adx":             regime_result["adx"],
        "bias_strength":   bias_result["strength"],
        "zone_strength":   zone_result["zone"].strength,
        "daily_direction": daily_align.get("daily_direction"),
    }
