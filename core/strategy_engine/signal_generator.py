"""core/strategy_engine/signal_generator.py — Multi-gate signal pipeline.

Pipeline (ICT Phase 1-3):
  Gate 0  : Circuit breakers (daily loss, max trades, correlation, news)
  Gate 1  : D1 market structure (HTFStructure — Phase 1)
  Gate 2  : H4 BOS bias aligned with D1 direction (Phase 1)
  Gate 3  : Order Block detection (Phase 2)
  Gate 3b : Fair Value Gap inside/near OB (Phase 3)
  Gate 4b : CHOCH on M5 (or M15 proxy)
  Gate 5  : Spread / risk check
  Gate 6  : Lot size sanity
  Gate 7  : Drawdown protocol
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from core.risk_engine.drawdown_monitor import evaluate_drawdown
from core.risk_engine.position_sizer import calculate_lot_size
from core.risk_engine.spread_filter import check_spread as check_risk_gate  # noqa: F401
from core.strategy_engine.bias_analyzer import BiasAnalyzer
from core.strategy_engine.choch_detector import detect_choch
from core.strategy_engine.fvg_detector import check_fvg
from core.strategy_engine.htf_structure import HTFStructure
from core.strategy_engine.news_filter import check_news_window
from core.strategy_engine.session_filter import is_valid_session
from core.structure_engine.order_block_detector import OrderBlockDetector

# Module-level instances — tests patch these by dotted path
_htf_struct = HTFStructure()        # Phase 1: D1 structure
_bias_anl   = BiasAnalyzer()
_ob_det     = OrderBlockDetector()  # Phase 2: Order Blocks
# Phase 3: FVG via check_fvg() function (stateless)

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
    open_trades: list[dict] | None = None,
    daily_pnl_r: float = 0.0,
    ltf_df: pd.DataFrame | None = None,   # M5 data for CHOCH (falls back to M15 if None)
) -> dict:
    """Run the full ICT signal pipeline and return a result dict."""
    now     = pd.Timestamp.now()
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
    for group in _CORR_GROUPS:
        if symbol in group:
            for ot in open_trades:
                if ot["pair"] in group and ot["pair"] != symbol:
                    return _blocked(0, f"correlated_pair_open_{ot['pair']}")

    # ── Gate 0e: News/event filter ────────────────────────────────────────────
    try:
        news = await check_news_window(symbol, now_utc)
        if not news["passed"]:
            return _blocked(0, f"news_window_{news.get('event', '')}")
    except Exception:
        pass  # calendar unavailable — allow trade

    # ── Gate 1: D1 Market Structure (Phase 1 — replaces H4 ADX regime) ───────
    regime_result = _htf_struct.classify(htf_df)
    if regime_result["signal_gate"] == "blocked":
        return _blocked(1, f"d1_structure_blocked_{regime_result.get('reason', '')}")

    # ── Gate 2: H4 BOS bias — must align with D1 structure ───────────────────
    bias_result = _bias_anl.analyze(htf_df, symbol)
    if not bias_result.get("direction"):
        return _blocked(2, "no_htf_bias")
    bias_result["symbol"] = symbol

    # Block if H4 bias contradicts D1 structure
    d1_bias = regime_result.get("d1_bias")
    if d1_bias and bias_result["direction"] != d1_bias:
        return _blocked(2, f"h4_bias_contradicts_d1_{d1_bias}")

    # ── Gate 3: Order Block (Phase 2 — replaces supply/demand zone) ──────────
    zone_result = _ob_det.check_gate(m15_df, bias_result["direction"])
    if not zone_result.get("passed"):
        return _blocked(3, "no_order_block")

    # ── Gate 3b: Fair Value Gap inside/near OB (Phase 3) ─────────────────────
    fvg_result = check_fvg(m15_df, bias_result["direction"])
    if not fvg_result.get("passed"):
        return _blocked(3, f"no_fvg_{fvg_result.get('reason', '')}")

    # ── Gate 4b: CHOCH on M5 (or M15 proxy if M5 unavailable) ───────────────
    choch_df     = ltf_df if (ltf_df is not None and len(ltf_df) >= 40) else m15_df
    choch_result = detect_choch(choch_df, bias_result["direction"])
    if not choch_result["passed"]:
        return _blocked(4, f"no_choch_{choch_result.get('reason', '')}")
    entry_result = choch_result  # CHOCH provides SL/TP

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
        "bias_strength":   bias_result.get("strength", 0.0),
        "zone_strength":   zone_result["zone"].strength if zone_result.get("zone") else 0.0,
        "d1_bias":         d1_bias,
        "fvg_top":         fvg_result.get("fvg_top"),
        "fvg_bottom":      fvg_result.get("fvg_bottom"),
    }
