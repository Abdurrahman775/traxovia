"""
tests/test_phase5.py — Phase 5 quality gate tests.

Five end-to-end tests validating the 7-gate signal pipeline, the drawdown
protocol, and the position-sizing interaction.  No live database, Redis, or
MT5 bridge required — all external dependencies are mocked.

Test 1 — Ranging regime blocks at Gate 1
    Build synthetic H4 + M15 OHLC data.
    Mock RegimeClassifier to return signal_gate='blocked'.
    Verify generate_signal returns gate=1, reason='regime_blocked', signal=None.

Test 2 — Stage 3 drawdown blocks at Gate 7
    Mock gates 1–6 to pass.
    Mock evaluate_drawdown to return stage=3, trading_allowed=False.
    Verify generate_signal returns gate=7, reason='dd_paused', signal=None.

Test 3 — Stage 1 DD transition at exactly 10.0%
    Call evaluate_drawdown directly with a mock DB returning dd_pct=10.0.
    Verify stage=1, trading_allowed=True.
    Verify the 0.5 % risk cap constant (_STAGE_RISK_CAP[1] == 0.005).
    Verify calculate_lot_size enforces that cap end-to-end.

Test 4 — Volatile regime halves lot_size vs trending
    Run generate_signal twice with identical inputs, changing only the regime.
    Verify lot_size_volatile == lot_size_trending × 0.5 (PositionSizer 0.5×).

Test 5 — All 7 gates pass → signal generated
    Mock all 7 gate dependencies to return valid passing results.
    Verify signal='generated', lot_size > 0, all required keys present.

Run:
    pytest tests/test_phase5.py -v
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# ── Pre-mock broken import chain ──────────────────────────────────────────────
# spread_filter → bridge_watchdog → notifications (runtime-only package).
# These two lines must execute before any test body imports check_risk_gate.
for _missing in ("notifications", "notifications.telegram_handler"):
    sys.modules.setdefault(_missing, MagicMock())

from core.risk_engine.drawdown_monitor import _STAGE_CFG, _classify_stage, evaluate_drawdown
from core.risk_engine.position_sizer import _STAGE_RISK_CAP, calculate_lot_size
from core.strategy_engine.signal_generator import generate_signal
from core.structure_engine.zone_detector import Zone


# ── OHLC helpers ───────────────────────────────────────────────────────────────

def _make_ohlc(n: int, freq: str = "h", seed: int = 0) -> pd.DataFrame:
    """
    Seeded random-walk OHLC suitable for both H4 and M15 data.
    All gate analyses are mocked, so the exact values are irrelevant —
    the DataFrames just need to be structurally valid (correct columns, n > 0).
    """
    rng    = np.random.default_rng(seed)
    close  = 1.0850 * np.exp(np.cumsum(rng.normal(0.0, 0.001, n)))
    open_  = np.empty(n);  open_[0] = close[0];  open_[1:] = close[:-1]
    hr     = np.abs(rng.normal(0.0, 0.0002, n))
    return pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq=freq),
        "open":  open_,
        "high":  np.maximum(open_, close) + hr,
        "low":   np.minimum(open_, close) - hr,
        "close": close,
    })


def _mock_db() -> AsyncMock:
    """Async DB stub — execute() and fetchrow() succeed silently."""
    db = AsyncMock()
    db.execute  = AsyncMock()
    db.fetchrow = AsyncMock(return_value=None)
    db.fetch    = AsyncMock(return_value=[])
    return db


# ── Gate mock payloads ─────────────────────────────────────────────────────────

def _regime(regime: str = "trending") -> dict:
    gate = {"trending": "open", "volatile": "reduced", "ranging": "blocked"}[regime]
    return {"regime": regime, "signal_gate": gate, "adx": 28.0, "atr_ratio": 1.2}


def _bias(direction: str | None = "bullish") -> dict:
    if direction is None:
        return {"direction": None, "strength": 0.0, "reason": "no_htf_bias"}
    return {"direction": direction, "strength": 0.8,
            "reason": f"{direction} bias — BOS 3 bars ago (strength=0.80)"}


def _zone_pass() -> dict:
    zone = Zone(
        zone_type="demand", top=1.0850, bottom=1.0840,
        strength=75.0, test_count=0, origin_index=5,
        created_at=pd.Timestamp("2024-01-01"),
    )
    return {"passed": True, "zone": zone, "reason": "price near demand zone boundary"}


def _entry_pass() -> dict:
    return {
        "passed": True, "entry_price": 1.0845, "sl_price": 1.0820,
        "tp_price": 1.0895, "sl_pips": 250.0, "tp_pips": 500.0,
        "reason": "bullish entry confirmed",
    }


def _risk_pass() -> dict:
    return {"allowed": True, "reason": "passed", "detail": {}}


def _dd_pass(stage: int = 0) -> dict:
    return {
        "user_id": "uid-1", "drawdown_pct": 3.0, "stage": stage,
        "stage_changed": False, "trading_allowed": True, "block_reason": None,
    }


def _dd_blocked(stage: int = 3) -> dict:
    return {
        "user_id": "uid-1", "drawdown_pct": 16.0, "stage": stage,
        "stage_changed": True, "trading_allowed": False,
        "block_reason": _STAGE_CFG[stage]["block_reason"],
    }


# ── Patch helper ──────────────────────────────────────────────────────────────

# (target, is_async, return_value)
_GATES_1_TO_6_PASS: list[tuple[str, bool, Any]] = [
    ("core.strategy_engine.signal_generator._regime_clf.classify", False, _regime()),
    ("core.strategy_engine.signal_generator._bias_anl.analyze",    False, _bias()),
    ("core.strategy_engine.signal_generator._zone_det.check_gate", False, _zone_pass()),
    ("core.strategy_engine.signal_generator._entry_anl.check_gate",False, _entry_pass()),
    ("core.strategy_engine.signal_generator.check_risk_gate",      True,  _risk_pass()),
]

_ALL_GATES_PASS: list[tuple[str, bool, Any]] = _GATES_1_TO_6_PASS + [
    ("core.strategy_engine.signal_generator.evaluate_drawdown", True, _dd_pass()),
]


@contextmanager
def _patches(spec: list[tuple[str, bool, Any]]):
    """Apply multiple patches simultaneously and restore them on exit."""
    patchers = []
    for target, is_async, rv in spec:
        p = (
            patch(target, new_callable=AsyncMock, return_value=rv)
            if is_async
            else patch(target, return_value=rv)
        )
        patchers.append(p)
        p.start()
    try:
        yield
    finally:
        for p in patchers:
            p.stop()


# ── Test 1 — Ranging regime blocks at Gate 1 ──────────────────────────────────

@pytest.mark.asyncio
async def test_ranging_regime_blocks_gate1():
    """
    A ranging regime (ADX < 20, signal_gate='blocked') must stop the pipeline
    at Gate 1 before any downstream analysis runs.
    """
    htf_df = _make_ohlc(200, freq="4h")
    m15_df = _make_ohlc(500, freq="15min")
    db     = _mock_db()

    with patch(
        "core.strategy_engine.signal_generator._regime_clf.classify",
        return_value=_regime("ranging"),
    ):
        result = await generate_signal("EURUSD", htf_df, m15_df, "uid-1", db)

    assert result["signal"] is None,          "Ranging regime must not generate a signal"
    assert result["gate"]   == 1,             "Block must occur at Gate 1"
    assert result["reason"] == "regime_blocked"
    assert result["symbol"] == "EURUSD"
    assert result["user_id"] == "uid-1"
    assert "timestamp" in result


# ── Test 2 — Stage 3 drawdown blocks at Gate 7 ────────────────────────────────

@pytest.mark.asyncio
async def test_stage3_drawdown_blocks_gate7():
    """
    When all gates 1–6 pass but drawdown is at stage 3 (≥ 15 %), the pipeline
    must block at Gate 7 with reason='dd_paused' and signal=None.
    """
    htf_df = _make_ohlc(200, freq="4h")
    m15_df = _make_ohlc(500, freq="15min")
    db     = _mock_db()

    gate7_blocked_spec = _GATES_1_TO_6_PASS + [
        ("core.strategy_engine.signal_generator.evaluate_drawdown",
         True, _dd_blocked(stage=3)),
    ]

    with _patches(gate7_blocked_spec):
        result = await generate_signal("EURUSD", htf_df, m15_df, "uid-1", db)

    assert result["signal"] is None,    "Stage-3 drawdown must not generate a signal"
    assert result["gate"]   == 7,       "Block must occur at Gate 7"
    assert result["reason"] == "dd_paused"


# ── Test 3 — Stage 1 transition at exactly 10.0 % drawdown ────────────────────

@pytest.mark.asyncio
async def test_stage1_transition_at_10pct_drawdown():
    """
    evaluate_drawdown with dd_pct=10.0 on a stage-0 account must:
      • return stage=1 and trading_allowed=True
      • trigger _apply_stage (stage changed 0→1)

    The 0.5 % risk cap defined in position_sizer must:
      • equal exactly 0.005 (_STAGE_RISK_CAP[1])
      • be enforced by calculate_lot_size: a 2 % risk request at stage 1
        must produce the same lot as a 0.5 % risk request at stage 0.
    """
    db = AsyncMock()
    db.execute  = AsyncMock()
    db.fetchrow = AsyncMock(return_value={
        "total_drawdown_pct": 10.0,
        "drawdown_stage":     0,
        "trading_allowed":    True,
        "block_reason":       None,
    })

    with patch(
        "core.risk_engine.drawdown_monitor._apply_stage",
        new_callable=AsyncMock,
    ) as mock_apply:
        result = await evaluate_drawdown("uid-1", db)

    # Stage classification and trading permission
    assert result["stage"]           == 1,    f"10 % DD must escalate to stage 1, got {result['stage']}"
    assert result["trading_allowed"] is True, "Stage 1 is caution, not a full block"
    assert result["stage_changed"]   is True, "_apply_stage must have been called"
    mock_apply.assert_awaited_once_with("uid-1", 1, 10.0, db)

    # Risk cap constant
    assert _STAGE_RISK_CAP[1] == pytest.approx(0.005), (
        f"Stage 1 risk cap must be 0.005 (0.5 %), got {_STAGE_RISK_CAP[1]}"
    )

    # End-to-end cap enforcement via calculate_lot_size
    # At 2 % unconstrained risk the lot should exceed the stage-1 cap.
    # At stage 1, the lot must be clamped to the 0.5 %-equivalent.
    lot_uncapped = calculate_lot_size(
        account_balance=10_000.0, risk_pct=0.02, sl_pips=100,
        symbol="EURUSD", regime="trending", dd_stage=0,
    )
    lot_stage1 = calculate_lot_size(
        account_balance=10_000.0, risk_pct=0.02, sl_pips=100,
        symbol="EURUSD", regime="trending", dd_stage=1,
    )
    lot_at_cap = calculate_lot_size(
        account_balance=10_000.0, risk_pct=0.005, sl_pips=100,
        symbol="EURUSD", regime="trending", dd_stage=0,
    )

    assert lot_stage1 < lot_uncapped, (
        "Stage-1 capped lot must be smaller than uncapped lot"
    )
    assert lot_stage1 == pytest.approx(lot_at_cap), (
        f"Stage-1 lot {lot_stage1} must equal 0.5 %-risk baseline {lot_at_cap}"
    )


# ── Test 4 — Volatile regime halves lot_size vs trending ──────────────────────

@pytest.mark.asyncio
async def test_volatile_regime_halves_lot_size():
    """
    Volatile regime applies a 0.5× multiplier inside PositionSizer.
    With identical symbol / SL / account inputs, volatile lot must equal
    trending lot × 0.5.
    """
    htf_df = _make_ohlc(200, freq="4h", seed=1)
    m15_df = _make_ohlc(500, freq="15min", seed=2)

    base = [
        ("core.strategy_engine.signal_generator._bias_anl.analyze",     False, _bias()),
        ("core.strategy_engine.signal_generator._zone_det.check_gate",  False, _zone_pass()),
        ("core.strategy_engine.signal_generator._entry_anl.check_gate", False, _entry_pass()),
        ("core.strategy_engine.signal_generator.check_risk_gate",       True,  _risk_pass()),
        ("core.strategy_engine.signal_generator.evaluate_drawdown",     True,  _dd_pass()),
    ]

    with _patches([("core.strategy_engine.signal_generator._regime_clf.classify",
                    False, _regime("trending"))] + base):
        res_trending = await generate_signal(
            "EURUSD", htf_df, m15_df, "uid-1", _mock_db(),
            account_balance=10_000.0, risk_pct=0.01,
        )

    with _patches([("core.strategy_engine.signal_generator._regime_clf.classify",
                    False, _regime("volatile"))] + base):
        res_volatile = await generate_signal(
            "EURUSD", htf_df, m15_df, "uid-1", _mock_db(),
            account_balance=10_000.0, risk_pct=0.01,
        )

    assert res_trending["signal"] == "generated", "Trending must generate a signal"
    assert res_volatile["signal"] == "generated", "Volatile must generate a signal"

    lot_t = res_trending["lot_size"]
    lot_v = res_volatile["lot_size"]

    assert lot_t > 0, "Trending lot must be positive"
    assert lot_v > 0, "Volatile lot must be positive"
    assert lot_v == pytest.approx(lot_t * 0.5), (
        f"Volatile lot {lot_v} must be exactly half of trending lot {lot_t}"
    )


# ── Test 5 — All 7 gates pass → signal generated ──────────────────────────────

@pytest.mark.asyncio
async def test_all_gates_pass_signal_generated():
    """
    When all 7 gate mocks return passing results generate_signal must:
      • return signal='generated'
      • return lot_size > 0
      • include every key specified in PRD Section 4.1
    """
    htf_df = _make_ohlc(200, freq="4h", seed=3)
    m15_df = _make_ohlc(500, freq="15min", seed=4)
    db     = _mock_db()

    with _patches(_ALL_GATES_PASS):
        result = await generate_signal(
            "EURUSD", htf_df, m15_df, "uid-1", db,
            account_balance=10_000.0, risk_pct=0.01,
        )

    assert result["signal"]   == "generated",  "Full pass must produce a generated signal"
    assert result["lot_size"] > 0,             "lot_size must be positive"
    assert result["gate"]     == 7,            "gate must equal 7 on full pass"

    required_keys = {
        "signal", "symbol", "direction", "entry_price", "sl_price",
        "tp_price", "sl_pips", "tp_pips", "lot_size", "regime",
        "adx", "bias_strength", "zone_strength", "gate", "timestamp", "user_id",
    }
    missing = required_keys - result.keys()
    assert not missing, f"Signal dict is missing required keys: {missing}"

    # Spot-check values propagated from gate mocks
    assert result["symbol"]      == "EURUSD"
    assert result["direction"]   == "bullish"
    assert result["entry_price"] == pytest.approx(1.0845)
    assert result["sl_pips"]     == pytest.approx(250.0)
    assert result["tp_pips"]     == pytest.approx(500.0)
    assert result["regime"]      == "trending"
    assert result["adx"]         == pytest.approx(28.0)
    assert result["bias_strength"] == pytest.approx(0.8)
    assert result["zone_strength"] == pytest.approx(75.0)


# ── Test 6 — Gate 2: no HTF bias blocks pipeline ──────────────────────────────

@pytest.mark.asyncio
async def test_no_htf_bias_blocks_gate2():
    """
    When bias_analyzer returns direction=None, the pipeline must block at
    Gate 2 with reason='no_htf_bias'.
    """
    htf_df = _make_ohlc(200, freq="4h")
    m15_df = _make_ohlc(500, freq="15min")
    db     = _mock_db()

    with patch(
        "core.strategy_engine.signal_generator._regime_clf.classify",
        return_value=_regime("trending"),
    ), patch(
        "core.strategy_engine.signal_generator._bias_anl.analyze",
        return_value=_bias(None),
    ):
        result = await generate_signal("EURUSD", htf_df, m15_df, "uid-1", db)

    assert result["signal"] is None
    assert result["gate"]   == 2
    assert result["reason"] == "no_htf_bias"


# ── Test 7 — Gate 3: no zone blocks pipeline ──────────────────────────────────

@pytest.mark.asyncio
async def test_no_zone_blocks_gate3():
    """
    When zone_detector returns passed=False, the pipeline must block at Gate 3.
    """
    htf_df = _make_ohlc(200, freq="4h")
    m15_df = _make_ohlc(500, freq="15min")
    db     = _mock_db()

    with patch(
        "core.strategy_engine.signal_generator._regime_clf.classify",
        return_value=_regime("trending"),
    ), patch(
        "core.strategy_engine.signal_generator._bias_anl.analyze",
        return_value=_bias("bullish"),
    ), patch(
        "core.strategy_engine.signal_generator._zone_det.check_gate",
        return_value={"passed": False, "zone": None, "reason": "no zone"},
    ):
        result = await generate_signal("EURUSD", htf_df, m15_df, "uid-1", db)

    assert result["signal"] is None
    assert result["gate"]   == 3
    assert result["reason"] == "no_zone"


# ── Test 8 — Gate 4: no entry confirmation blocks pipeline ────────────────────

@pytest.mark.asyncio
async def test_no_entry_blocks_gate4():
    """
    When entry_analyzer returns passed=False, the pipeline must block at Gate 4.
    """
    htf_df = _make_ohlc(200, freq="4h")
    m15_df = _make_ohlc(500, freq="15min")
    db     = _mock_db()

    with patch(
        "core.strategy_engine.signal_generator._regime_clf.classify",
        return_value=_regime("trending"),
    ), patch(
        "core.strategy_engine.signal_generator._bias_anl.analyze",
        return_value=_bias("bullish"),
    ), patch(
        "core.strategy_engine.signal_generator._zone_det.check_gate",
        return_value=_zone_pass(),
    ), patch(
        "core.strategy_engine.signal_generator._entry_anl.check_gate",
        return_value={"passed": False, "reason": "no entry pattern"},
    ):
        result = await generate_signal("EURUSD", htf_df, m15_df, "uid-1", db)

    assert result["signal"] is None
    assert result["gate"]   == 4
    assert result["reason"] == "no_entry"


# ── Test 9 — Gate 5: risk blocked ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_risk_blocked_gate5():
    """
    When check_risk_gate returns allowed=False, the pipeline must block at Gate 5.
    """
    htf_df = _make_ohlc(200, freq="4h")
    m15_df = _make_ohlc(500, freq="15min")
    db     = _mock_db()

    spec = [
        ("core.strategy_engine.signal_generator._regime_clf.classify", False, _regime()),
        ("core.strategy_engine.signal_generator._bias_anl.analyze",    False, _bias()),
        ("core.strategy_engine.signal_generator._zone_det.check_gate", False, _zone_pass()),
        ("core.strategy_engine.signal_generator._entry_anl.check_gate",False, _entry_pass()),
        ("core.strategy_engine.signal_generator.check_risk_gate",      True,
         {"allowed": False, "reason": "spread too wide", "detail": {}}),
    ]

    with _patches(spec):
        result = await generate_signal("EURUSD", htf_df, m15_df, "uid-1", db)

    assert result["signal"] is None
    assert result["gate"]   == 5
    assert result["reason"] == "risk_blocked"


# ── Test 10 — Stage 2 drawdown caps risk at 0.25% ─────────────────────────────

@pytest.mark.asyncio
async def test_stage2_drawdown_caps_risk():
    """
    evaluate_drawdown with dd_pct=12.0 on a stage-0 account must:
      • return stage=2 and trading_allowed=True
      • _STAGE_RISK_CAP[2] == 0.0025
      • calculate_lot_size at stage 2 equals the 0.25%-risk baseline
    """
    db = AsyncMock()
    db.execute  = AsyncMock()
    db.fetchrow = AsyncMock(return_value={
        "total_drawdown_pct": 12.0,
        "drawdown_stage":     0,
        "trading_allowed":    True,
        "block_reason":       None,
    })

    with patch("core.risk_engine.drawdown_monitor._apply_stage", new_callable=AsyncMock):
        result = await evaluate_drawdown("uid-1", db)

    assert result["stage"]           == 2
    assert result["trading_allowed"] is True
    assert result["stage_changed"]   is True

    assert _STAGE_RISK_CAP[2] == pytest.approx(0.0025)

    lot_stage2 = calculate_lot_size(10_000, 0.02, 100, "EURUSD", "trending", 2)
    lot_at_cap = calculate_lot_size(10_000, 0.0025, 100, "EURUSD", "trending", 0)
    assert lot_stage2 == pytest.approx(lot_at_cap)


# ── Test 11 — No stage change when already at correct stage ───────────────────

@pytest.mark.asyncio
async def test_no_stage_change_when_already_correct():
    """
    evaluate_drawdown must not call _apply_stage when the current stage
    already matches the computed stage.
    """
    db = AsyncMock()
    db.execute  = AsyncMock()
    db.fetchrow = AsyncMock(return_value={
        "total_drawdown_pct": 11.0,
        "drawdown_stage":     1,   # already at stage 1
        "trading_allowed":    True,
        "block_reason":       None,
    })

    with patch(
        "core.risk_engine.drawdown_monitor._apply_stage",
        new_callable=AsyncMock,
    ) as mock_apply:
        result = await evaluate_drawdown("uid-1", db)

    assert result["stage"]         == 1
    assert result["stage_changed"] is False
    mock_apply.assert_not_awaited()


# ── Test 12 — evaluate_drawdown returns stage 0 when no row ───────────────────

@pytest.mark.asyncio
async def test_evaluate_drawdown_no_row_returns_stage0():
    """
    When risk_state has no row for today, evaluate_drawdown must return
    stage=0, trading_allowed=True, drawdown_pct=0.0.
    """
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value=None)

    result = await evaluate_drawdown("uid-1", db)

    assert result["stage"]           == 0
    assert result["trading_allowed"] is True
    assert result["drawdown_pct"]    == 0.0
    assert result["stage_changed"]   is False


# ── Test 13 — Lot size: XAU pair uses 100 pip value ──────────────────────────

def test_lot_size_xau_pair():
    """XAU pairs use pip_value=100 per lot (between JPY=1000 and standard=10)."""
    lot_eur = calculate_lot_size(10_000, 0.01, 20, "EURUSD", "trending", 0)
    lot_xau = calculate_lot_size(10_000, 0.01, 20, "XAUUSD", "trending", 0)

    assert lot_xau < lot_eur, (
        f"XAU pair should produce smaller lot: EURUSD={lot_eur}, XAUUSD={lot_xau}"
    )
    assert lot_xau > 0, "XAU lot must be positive"


# ── Test 14 — Signal result always has symbol and user_id ─────────────────────

@pytest.mark.asyncio
async def test_blocked_signal_always_has_symbol_and_user_id():
    """
    Every blocked result (any gate) must include symbol and user_id.
    """
    htf_df = _make_ohlc(200, freq="4h")
    m15_df = _make_ohlc(500, freq="15min")
    db     = _mock_db()

    with patch(
        "core.strategy_engine.signal_generator._regime_clf.classify",
        return_value=_regime("ranging"),
    ):
        result = await generate_signal("GBPUSD", htf_df, m15_df, "uid-99", db)

    assert result["symbol"]  == "GBPUSD"
    assert result["user_id"] == "uid-99"
    assert "timestamp" in result


# ── Test 15 — _classify_stage: all boundary values ────────────────────────────

@pytest.mark.parametrize("dd_pct,expected_stage", [
    (0.0,  0),
    (9.99, 0),
    (10.0, 1),
    (11.5, 1),
    (12.0, 2),
    (14.9, 2),
    (15.0, 3),
    (25.0, 3),
])
def test_classify_stage_parametrized(dd_pct, expected_stage):
    """_classify_stage must return the correct stage for all boundary values."""
    from core.risk_engine.drawdown_monitor import _classify_stage
    assert _classify_stage(dd_pct) == expected_stage, (
        f"dd_pct={dd_pct}: expected stage {expected_stage}, "
        f"got {_classify_stage(dd_pct)}"
    )


# ── Test 16 — Lot size: zero SL returns zero ──────────────────────────────────

def test_lot_size_zero_sl_returns_zero():
    """calculate_lot_size with sl_pips=0 must return 0.0 (avoid division by zero)."""
    lot = calculate_lot_size(10_000, 0.01, 0, "EURUSD", "trending", 0)
    assert lot == 0.0, f"sl_pips=0 must return 0.0, got {lot}"


# ── Test 17 — Lot size: stage 3 always returns zero ──────────────────────────

@pytest.mark.parametrize("regime", ["trending", "ranging", "volatile"])
def test_lot_size_stage3_always_zero(regime):
    """Stage 3 must return 0.0 for all regime types."""
    lot = calculate_lot_size(10_000, 0.02, 20, "EURUSD", regime, 3)
    assert lot == 0.0, f"Stage 3 + {regime} must return 0.0, got {lot}"


# ── Test 18 — Signal pipeline: result has timestamp ───────────────────────────

@pytest.mark.asyncio
async def test_generated_signal_has_timestamp():
    """A generated signal must include a timestamp."""
    htf_df = _make_ohlc(200, freq="4h", seed=5)
    m15_df = _make_ohlc(500, freq="15min", seed=6)
    db     = _mock_db()

    with _patches(_ALL_GATES_PASS):
        result = await generate_signal(
            "EURUSD", htf_df, m15_df, "uid-1", db,
            account_balance=10_000.0, risk_pct=0.01,
        )

    assert "timestamp" in result
    assert result["timestamp"] is not None


# ── Test 19 — Drawdown: stage 3 block_reason is set ──────────────────────────

def test_stage3_block_reason_is_set():
    """Stage 3 config must have a non-None block_reason."""
    from core.risk_engine.drawdown_monitor import _STAGE_CFG

    assert _STAGE_CFG[3]["block_reason"] is not None
    assert len(_STAGE_CFG[3]["block_reason"]) > 0


# ── Test 20 — Lot size: trending > volatile for same inputs ──────────────────

def test_trending_lot_greater_than_volatile():
    """Trending lot must always be greater than volatile lot (0.5× multiplier)."""
    for balance in (5_000, 10_000, 50_000):
        lot_t = calculate_lot_size(balance, 0.01, 20, "EURUSD", "trending", 0)
        lot_v = calculate_lot_size(balance, 0.01, 20, "EURUSD", "volatile", 0)
        assert lot_t > lot_v, (
            f"balance={balance}: trending lot {lot_t} must exceed volatile lot {lot_v}"
        )
