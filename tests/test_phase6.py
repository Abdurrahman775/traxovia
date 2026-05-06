"""
tests/test_phase6.py — Phase 6 quality gate tests.

Six tests validating the AI engine pipeline end-to-end.  No live database,
Redis, or MT5 bridge required — all external dependencies are mocked.

Test 1 — Feature store receives exactly 50 features
    Call FeatureEngineer.extract() with a full synthetic signal context.
    Verify exactly 50 keys are returned and every value is finite.

Test 2 — Feedback loop writes correct outcome labels
    Three parametrised sub-cases:
      pnl_r =  1.5  → outcome = 'win'
      pnl_r = -0.8  → outcome = 'loss'
      pnl_r =  0.05 → outcome = 'breakeven'

Test 3 — Correction 2.2: audit_log INSERT supplies exactly 3 bind values
    Reproduce the original bug (2 bind params for 3 placeholders) and confirm
    the fixed code passes user_id, action, AND detail as $1/$2/$3.

Test 4 — Model trainer raises ValueError with < 50 samples
    Mock the feature_store query to return 49 rows; assert ValueError.

Test 5 — ModelPredictor returns correct confidence tiers
    probability = 0.75 → 'high'
    probability = 0.60 → 'medium'
    probability = 0.45 → 'low'

Test 6 — Correction 2.3: shap_analyzer Celery task uses get_sync_db (psycopg2)
    Call calculate_shap_async() with all dependencies mocked.
    Assert get_sync_db was invoked (sync psycopg2 path).
    Assert no asyncpg async methods appear in the function source.

Run:
    pytest tests/test_phase6.py -v
"""

from __future__ import annotations

import sys
import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# ── Pre-mock all absent / runtime-only dependencies ────────────────────────────
# Must execute before any test-subject imports so that module-level import
# statements in those modules resolve to MagicMocks, not ImportErrors.
_MOCKED_MODULES = (
    "shap",
    "database",
    "database.connection",
    "database.sync_connection",
    "notifications",
    "notifications.telegram_handler",
    "notifications.websocket_manager",
    "scheduler",
    "scheduler.tasks",
    "telegram",
)
_pre_existing = {m for m in _MOCKED_MODULES if m in sys.modules}
for _missing in _MOCKED_MODULES:
    sys.modules.setdefault(_missing, MagicMock())

from core.ai_engine.feature_engineer import FeatureEngineer
from core.ai_engine.feedback_loop    import on_trade_closed
from core.ai_engine.model_trainer    import WalkForwardTrainer, FEATURE_NAMES
from core.ai_engine.model_predictor  import ModelPredictor
from core.ai_engine.model_manager    import ModelManager

# Remove only the modules that would pollute later test files.
# Keep 'shap' — it's needed by shap_analyzer which is imported below.
_REMOVE_AFTER_IMPORT = (
    "database",
    "database.connection",
    "database.sync_connection",
    "notifications",
    "notifications.telegram_handler",
    "notifications.websocket_manager",
    "scheduler",
    "scheduler.tasks",
    "telegram",
)
from core.ai_engine.shap_analyzer    import calculate_shap_async

# Remove mocks that would pollute later test files needing real implementations.
# Keep 'shap' — shap_analyzer holds a reference to it already.
for _m in _REMOVE_AFTER_IMPORT:
    if _m not in _pre_existing:
        sys.modules.pop(_m, None)


# ── Shared OHLC / context helpers ─────────────────────────────────────────────

def _make_ohlc(n: int, freq: str = "h", seed: int = 0) -> pd.DataFrame:
    rng   = np.random.default_rng(seed)
    close = 1.0850 * np.exp(np.cumsum(rng.normal(0.0, 0.001, n)))
    open_ = np.empty(n); open_[0] = close[0]; open_[1:] = close[:-1]
    hr    = np.abs(rng.normal(0.0, 0.0002, n))
    return pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq=freq),
        "open":  open_,
        "high":  np.maximum(open_, close) + hr,
        "low":   np.minimum(open_, close) - hr,
        "close": close,
    })


def _signal_context() -> dict:
    from core.structure_engine.zone_detector import Zone
    htf = _make_ohlc(200, "4h",   seed=10)
    ltf = _make_ohlc(500, "15min", seed=11)
    zone = Zone(
        zone_type="demand", top=1.0850, bottom=1.0840,
        strength=75.0, test_count=0, origin_index=5,
        created_at=pd.Timestamp("2024-01-01"),
    )
    return {
        "symbol":      "EURUSD",
        "htf_df":      htf,
        "ltf_df":      ltf,
        "regime_info": {"regime": "trending", "signal_gate": "open",
                        "adx": 28.0, "atr_ratio": 1.1},
        "bias_info":   {"direction": "bullish", "strength": 0.8, "reason": "bullish"},
        "zone_info":   {"passed": True, "zone": zone, "reason": "near demand zone"},
        "entry_info":  {"passed": True, "entry_price": 1.0845, "sl_price": 1.0820,
                        "tp_price": 1.0895, "sl_pips": 250.0, "tp_pips": 500.0,
                        "reason": "confirmed"},
        "weekly_bias": {"direction": "bullish", "bos_strength": 0.7,
                        "bars_since_weekly_bos": 3},
        "spread":      {"current_spread": 0.8, "baseline": 1.0},
        "user_id":     "uid-1",
        "timestamp":   pd.Timestamp("2024-01-15 10:00:00"),
    }


# ── Feedback loop helpers ──────────────────────────────────────────────────────

def _async_db(trade: dict, signal: dict) -> AsyncMock:
    db = AsyncMock()
    db.fetchrow = AsyncMock(side_effect=[trade, signal])
    db.execute  = AsyncMock()
    return db


def _mock_db_direct(db):
    """Wrap db in an async context manager mock for patching get_db_direct."""
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=db)
    mock_cm.__aexit__  = AsyncMock(return_value=False)
    return MagicMock(return_value=mock_cm)


def _trade(pnl_r: float) -> dict:
    return {"id": "t1", "signal_id": "s1", "pnl_r": pnl_r,
            "pips": 25, "duration_hours": 4.0}


def _signal() -> dict:
    return {"id": "s1", "pair": "EURUSD", "direction": "bullish",
            "triggered_at": "2024-01-15T10:00:00", "community_visible": False}


# ── Psycopg2-style mock context manager ───────────────────────────────────────

@contextmanager
def _sync_db_ctx(fetchall_val=None, fetchone_val=None):
    cur = MagicMock()
    cur.fetchall.return_value  = fetchall_val or []
    cur.fetchone.return_value  = fetchone_val

    conn = MagicMock()
    conn.__enter__ = lambda s: conn
    conn.__exit__  = lambda s, *a: None
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__  = lambda s, *a: None

    with patch("database.sync_connection.get_sync_db", return_value=conn):
        yield conn, cur


# ── Model trainer helper ───────────────────────────────────────────────────────

def _feature_rows(n: int) -> list[tuple]:
    rng  = np.random.default_rng(42)
    feat = {name: float(rng.uniform(0, 1)) for name in FEATURE_NAMES}
    outcomes = ["win" if i % 3 != 0 else "loss" for i in range(n)]
    return [(json.dumps(feat), outcomes[i], 1.5 if outcomes[i] == "win" else -1.0)
            for i in range(n)]


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Feature store receives exactly 50 features
# ═══════════════════════════════════════════════════════════════════════════════

def test_feature_store_gets_50_features():
    """
    FeatureEngineer.extract() must return exactly 50 features, all finite floats.
    Validates that the complete extraction pipeline runs without error and that
    no category silently returns None or NaN values.
    """
    ctx      = _signal_context()
    features = FeatureEngineer().extract(ctx)

    assert len(features) == 50, (
        f"Expected 50 features, got {len(features)}.\n"
        f"Keys: {sorted(features)}"
    )

    bad = {k: v for k, v in features.items()
           if not isinstance(v, (int, float)) or not np.isfinite(v)}
    assert not bad, f"Non-finite feature values: {bad}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Feedback loop writes correct outcome labels
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("pnl_r,expected_outcome", [
    ( 1.5,  "win"),
    (-0.8,  "loss"),
    ( 0.05, "breakeven"),
])
async def test_feedback_loop_outcome_labels(pnl_r: float, expected_outcome: str):
    """
    on_trade_closed() must map pnl_r to the correct outcome label in the
    feature_store UPDATE:
      pnl_r >  0.1  → 'win'
      pnl_r < -0.1  → 'loss'
      otherwise     → 'breakeven'
    """
    db = _async_db(_trade(pnl_r), _signal())

    with patch("core.ai_engine.feedback_loop.get_db_direct", _mock_db_direct(db)), \
         patch("core.ai_engine.feedback_loop.trigger_retrain_if_needed",
               AsyncMock()):
        await on_trade_closed("t1", "uid-1")

    # First execute() call is the feature_store UPDATE; args[1] = outcome label
    feature_store_call = db.execute.call_args_list[0]
    actual_outcome     = feature_store_call.args[1]

    assert actual_outcome == expected_outcome, (
        f"pnl_r={pnl_r}: expected outcome='{expected_outcome}', "
        f"got '{actual_outcome}'"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Correction 2.2: audit_log INSERT has exactly 3 bind values
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_correction_2_2_audit_log_has_3_bind_values():
    """
    Correction 2.2 regression guard: the audit_log INSERT must supply 3 positional
    bind values — (user_id, action, detail) — matching VALUES($1,$2,$3).

    The pre-fix bug passed only (user_id, outcome) → $3 was unbound → crash.
    """
    db = _async_db(_trade(1.5), _signal())

    with patch("core.ai_engine.feedback_loop.get_db_direct", _mock_db_direct(db)), \
         patch("core.ai_engine.feedback_loop.trigger_retrain_if_needed",
               AsyncMock()):
        await on_trade_closed("t1", "uid-1")

    audit_calls = [
        c for c in db.execute.call_args_list
        if "audit_log" in c.args[0]
    ]
    assert len(audit_calls) == 1, "Expected exactly one audit_log INSERT"

    bind_values = audit_calls[0].args[1:]   # strip the SQL string

    assert len(bind_values) == 3, (
        f"audit_log INSERT must pass 3 bind values ($1, $2, $3), "
        f"got {len(bind_values)}: {bind_values}"
    )
    assert bind_values[0] == "uid-1",        f"$1 must be user_id, got {bind_values[0]!r}"
    assert bind_values[1] == "trade_closed", f"$2 must be action, got {bind_values[1]!r}"
    assert isinstance(bind_values[2], str) and len(bind_values[2]) > 0, (
        f"$3 (detail) must be a non-empty string, got {bind_values[2]!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Model trainer raises ValueError with < 50 samples
# ═══════════════════════════════════════════════════════════════════════════════

def test_model_trainer_raises_valueerror_under_50_samples():
    """
    WalkForwardTrainer.run() must raise ValueError when the feature_store
    returns fewer than 50 labeled samples, with a message referencing the 50-
    sample minimum.
    """
    import tempfile
    trainer = WalkForwardTrainer(models_dir=tempfile.mkdtemp())

    with _sync_db_ctx(fetchall_val=_feature_rows(49), fetchone_val=(1,)):
        with pytest.raises(ValueError, match="50"):
            trainer.run()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — ModelPredictor returns correct confidence tiers
# ═══════════════════════════════════════════════════════════════════════════════

def test_model_predictor_confidence_tiers():
    """
    Confidence tier boundaries (applied to signal_probability):
      >= 0.70 → 'high'
      >= 0.55 → 'medium'
      <  0.55 → 'low'

    Three cases verified: 0.75 (high), 0.60 (medium), 0.45 (low).
    """
    cases = [
        (0.75, "high"),
        (0.60, "medium"),
        (0.45, "low"),
    ]
    features = {name: 0.5 for name in FEATURE_NAMES}

    for prob, expected_tier in cases:
        model = MagicMock()
        model.predict_proba.return_value = np.array([[1 - prob, prob]])
        model.feature_importances_       = np.linspace(0.1, 1.0, 50)

        manager = MagicMock(spec=ModelManager)
        manager.get_model.return_value          = model
        manager.get_active_version.return_value = {
            "id": 1, "model_path": "models/v1.pkl",
            "oos_sharpe": 1.85, "oos_win_rate": 0.62,
            "trained_at": "2024-01-15",
        }

        predictor = ModelPredictor(manager=manager)
        result    = predictor.predict(features)

        assert result["confidence_tier"] == expected_tier, (
            f"prob={prob}: expected '{expected_tier}', "
            f"got '{result['confidence_tier']}'"
        )
        assert result["signal_probability"] == pytest.approx(prob, abs=1e-6), (
            f"signal_probability mismatch for prob={prob}: {result['signal_probability']}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — Correction 2.3: shap_analyzer uses get_sync_db, not asyncpg
# ═══════════════════════════════════════════════════════════════════════════════

def test_correction_2_3_shap_uses_sync_db():
    """
    Correction 2.3 regression guard: calculate_shap_async() must use
    get_sync_db() (psycopg2) for all DB access, never asyncpg async methods.

    Two assertions:
      1. Functional — get_sync_db is called at least once during task execution.
      2. Static    — the module source contains no asyncpg import or 'await db.'
                     patterns that would deadlock inside a Celery worker.
    """
    import inspect
    from core.ai_engine import shap_analyzer as _sa

    # Build a psycopg2-style cursor that returns a valid signal row
    ai_features_json = json.dumps({name: 0.5 for name in FEATURE_NAMES})
    columns          = ["id", "user_id", "ai_features"]
    row              = ("signal-1", "uid-1", ai_features_json)

    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.description           = [(col,) for col in columns]

    conn = MagicMock()
    conn.__enter__ = lambda s: conn
    conn.__exit__  = lambda s, *a: None
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__  = lambda s, *a: None

    # Mock SHAP explainer: shap_values returns list-of-list shape (1, 50)
    mock_explainer = MagicMock()
    mock_explainer.shap_values.return_value = [[0.1] * 50]

    # get_sync_db is imported at module level in shap_analyzer — patch there.
    with patch("core.ai_engine.shap_analyzer.get_sync_db",
               return_value=conn) as mock_get_sync_db, \
         patch("core.ai_engine.shap_analyzer.get_active_model",
               return_value=MagicMock()), \
         patch("core.ai_engine.shap_analyzer.shap.TreeExplainer",
               return_value=mock_explainer), \
         patch("asyncio.run"):       # prevent real event-loop creation in the test
        calculate_shap_async("signal-1")

    # ── Assertion 1: sync DB path was used ────────────────────────────────────
    assert mock_get_sync_db.call_count >= 1, (
        "get_sync_db must be called inside calculate_shap_async "
        "(Correction 2.3 — psycopg2, not asyncpg)"
    )

    # ── Assertion 2: no asyncpg patterns in the task source ───────────────────
    src = inspect.getsource(_sa.calculate_shap_async)
    assert "asyncpg" not in src, (
        "calculate_shap_async source must not reference asyncpg"
    )
    assert "await db." not in src, (
        "calculate_shap_async must not use 'await db.' — async calls deadlock "
        "inside Celery workers (Correction 2.3)"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7 — Feature engineer: supply zone features
# ═══════════════════════════════════════════════════════════════════════════════

def test_feature_engineer_supply_zone():
    """
    When the zone is a supply zone, in_supply_zone=1.0 and in_demand_zone=0.0.
    """
    from core.structure_engine.zone_detector import Zone

    ctx = _signal_context()
    supply_zone = Zone(
        zone_type="supply", top=1.0900, bottom=1.0890,
        strength=65.0, test_count=1, origin_index=10,
        created_at=pd.Timestamp("2024-01-01"),
    )
    ctx["zone_info"]["zone"] = supply_zone

    features = FeatureEngineer().extract(ctx)

    assert features["in_supply_zone"] == 1.0, "supply zone must set in_supply_zone=1.0"
    assert features["in_demand_zone"] == 0.0, "supply zone must set in_demand_zone=0.0"
    assert features["zone_strength"]  == pytest.approx(65.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8 — Feature engineer: bearish bias features
# ═══════════════════════════════════════════════════════════════════════════════

def test_feature_engineer_bearish_bias():
    """
    When bias direction is 'bearish', bias_bullish=0.0 and weekly_bias_bullish=0.0.
    """
    ctx = _signal_context()
    ctx["bias_info"]["direction"] = "bearish"
    ctx["weekly_bias"]["direction"] = "bearish"

    features = FeatureEngineer().extract(ctx)

    assert features["bias_bullish"]        == 0.0
    assert features["weekly_bias_bullish"] == 0.0
    assert features["weekly_bearish"]      == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 9 — Feature engineer: time features are in valid range
# ═══════════════════════════════════════════════════════════════════════════════

def test_feature_engineer_time_features_valid_range():
    """
    hour_sin, hour_cos, day_sin, day_cos must all be in [-1, 1].
    session_london must be 0.0 or 1.0.
    """
    ctx = _signal_context()
    features = FeatureEngineer().extract(ctx)

    for key in ("hour_sin", "hour_cos", "day_sin", "day_cos"):
        assert -1.0 <= features[key] <= 1.0, (
            f"{key}={features[key]} is outside [-1, 1]"
        )
    assert features["session_london"] in (0.0, 1.0), (
        f"session_london must be 0.0 or 1.0, got {features['session_london']}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 10 — Feature engineer: FEATURE_NAMES has exactly 50 entries
# ═══════════════════════════════════════════════════════════════════════════════

def test_feature_names_has_50_entries():
    """FEATURE_NAMES constant must have exactly 50 unique entries."""
    assert len(FEATURE_NAMES) == 50, (
        f"FEATURE_NAMES must have 50 entries, got {len(FEATURE_NAMES)}"
    )
    assert len(set(FEATURE_NAMES)) == 50, "FEATURE_NAMES must have no duplicates"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 11 — Model trainer: succeeds with exactly 50 samples
# ═══════════════════════════════════════════════════════════════════════════════

def test_model_trainer_succeeds_with_50_samples():
    """WalkForwardTrainer.run() must succeed (not raise) with exactly 50 samples."""
    import tempfile
    trainer = WalkForwardTrainer(models_dir=tempfile.mkdtemp())

    with _sync_db_ctx(fetchall_val=_feature_rows(50), fetchone_val=(1,)):
        result = trainer.run()

    assert "version"    in result
    assert "model_path" in result
    assert result["samples"] == 50


# ═══════════════════════════════════════════════════════════════════════════════
# Test 12 — Model trainer: returns oos_sharpe and oos_wr
# ═══════════════════════════════════════════════════════════════════════════════

def test_model_trainer_returns_metrics():
    """WalkForwardTrainer.run() must return oos_sharpe and oos_wr."""
    import tempfile
    trainer = WalkForwardTrainer(models_dir=tempfile.mkdtemp())

    with _sync_db_ctx(fetchall_val=_feature_rows(100), fetchone_val=(1,)):
        result = trainer.run()

    assert "oos_sharpe" in result
    assert "oos_wr"     in result
    assert isinstance(result["oos_sharpe"], float)
    assert isinstance(result["oos_wr"],     float)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 13 — ModelPredictor: predict returns all required keys
# ═══════════════════════════════════════════════════════════════════════════════

def test_model_predictor_returns_required_keys():
    """ModelPredictor.predict() must return all required keys."""
    import numpy as np

    features = {name: 0.5 for name in FEATURE_NAMES}
    model    = MagicMock()
    model.predict_proba.return_value      = np.array([[0.3, 0.7]])
    model.feature_importances_            = np.linspace(0.1, 1.0, 50)

    manager = MagicMock(spec=ModelManager)
    manager.get_model.return_value          = model
    manager.get_active_version.return_value = {
        "id": 1, "model_path": "models/v1.pkl",
        "oos_sharpe": 1.5, "oos_win_rate": 0.60,
        "trained_at": "2024-01-15",
    }

    predictor = ModelPredictor(manager=manager)
    result    = predictor.predict(features)

    for key in ("signal_probability", "confidence_tier", "top_features", "model_version"):
        assert key in result, f"Missing key '{key}' in predict() result"

    assert len(result["top_features"]) == 5, "top_features must have 5 entries"
    assert result["model_version"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test 14 — Feedback loop: community_visible trade triggers post_result_drop
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_feedback_loop_community_visible_triggers_drop():
    """
    When signal.community_visible=True, on_trade_closed must call
    post_result_drop exactly once.
    """
    db = _async_db(
        _trade(1.5),
        {**_signal(), "community_visible": True},
    )

    mock_post = AsyncMock()

    with patch("core.ai_engine.feedback_loop.get_db_direct", _mock_db_direct(db)), \
         patch("core.ai_engine.feedback_loop.trigger_retrain_if_needed", AsyncMock()), \
         patch("telegram.community_drops.post_result_drop", mock_post):
        await on_trade_closed("t1", "uid-1")

    mock_post.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 15 — SHAP: generate_plain_english_summary formats correctly
# ═══════════════════════════════════════════════════════════════════════════════

def test_shap_plain_english_summary():
    """generate_plain_english_summary must produce a non-empty string."""
    from core.ai_engine.shap_analyzer import generate_plain_english_summary

    top_pos = [("adx", 0.35), ("bias_strength", 0.20)]
    top_neg = [("spread_ratio", -0.15)]

    summary = generate_plain_english_summary(top_pos, top_neg)

    assert isinstance(summary, str)
    assert len(summary) > 0
    assert "adx" in summary
    assert "spread_ratio" in summary


# ═══════════════════════════════════════════════════════════════════════════════
# Test 16 — SHAP: empty feature lists produce fallback message
# ═══════════════════════════════════════════════════════════════════════════════

def test_shap_plain_english_summary_empty():
    """generate_plain_english_summary with empty lists returns fallback message."""
    from core.ai_engine.shap_analyzer import generate_plain_english_summary

    summary = generate_plain_english_summary([], [])

    assert isinstance(summary, str)
    assert len(summary) > 0  # fallback message, not empty string


# ═══════════════════════════════════════════════════════════════════════════════
# Test 17 — Feature engineer: spread_ratio computed correctly
# ═══════════════════════════════════════════════════════════════════════════════

def test_feature_engineer_spread_ratio():
    """spread_ratio must equal current_spread / baseline."""
    ctx = _signal_context()
    ctx["spread"] = {"current_spread": 1.5, "baseline": 3.0}

    features = FeatureEngineer().extract(ctx)

    assert features["current_spread"]  == pytest.approx(1.5)
    assert features["spread_baseline"] == pytest.approx(3.0)
    assert features["spread_ratio"]    == pytest.approx(0.5)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 18 — Feature engineer: rr_ratio computed correctly
# ═══════════════════════════════════════════════════════════════════════════════

def test_feature_engineer_rr_ratio():
    """rr_ratio must equal tp_pips / sl_pips."""
    ctx = _signal_context()
    ctx["entry_info"]["sl_pips"] = 200.0
    ctx["entry_info"]["tp_pips"] = 400.0

    features = FeatureEngineer().extract(ctx)

    assert features["rr_ratio"] == pytest.approx(2.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 19 — Feedback loop: trigger_retrain_if_needed is called
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_feedback_loop_calls_trigger_retrain():
    """on_trade_closed must call trigger_retrain_if_needed after labeling."""
    db = _async_db(_trade(1.5), _signal())

    mock_retrain = AsyncMock()

    with patch("core.ai_engine.feedback_loop.get_db_direct", _mock_db_direct(db)), \
         patch("core.ai_engine.feedback_loop.trigger_retrain_if_needed", mock_retrain):
        await on_trade_closed("t1", "uid-1")

    mock_retrain.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 20 — Feedback loop: feature_store UPDATE is called
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_feedback_loop_updates_feature_store():
    """on_trade_closed must call db.execute at least twice (feature_store + audit_log)."""
    db = _async_db(_trade(2.0), _signal())

    with patch("core.ai_engine.feedback_loop.get_db_direct", _mock_db_direct(db)), \
         patch("core.ai_engine.feedback_loop.trigger_retrain_if_needed", AsyncMock()):
        await on_trade_closed("t1", "uid-1")

    assert db.execute.call_count >= 2, (
        f"Expected at least 2 db.execute calls (feature_store + audit_log), "
        f"got {db.execute.call_count}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 21 — ModelPredictor: high confidence tier at 0.70 boundary
# ═══════════════════════════════════════════════════════════════════════════════

def test_model_predictor_high_tier_at_boundary():
    """probability=0.70 must produce 'high' confidence tier (inclusive boundary)."""
    import numpy as np

    features = {name: 0.5 for name in FEATURE_NAMES}
    model    = MagicMock()
    model.predict_proba.return_value = np.array([[0.30, 0.70]])
    model.feature_importances_       = np.ones(50)

    manager = MagicMock(spec=ModelManager)
    manager.get_model.return_value          = model
    manager.get_active_version.return_value = {
        "id": 2, "model_path": "models/v2.pkl",
        "oos_sharpe": 1.2, "oos_win_rate": 0.58, "trained_at": "2024-02-01",
    }

    predictor = ModelPredictor(manager=manager)
    result    = predictor.predict(features)

    assert result["confidence_tier"] == "high", (
        f"prob=0.70 must be 'high', got '{result['confidence_tier']}'"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 22 — ModelPredictor: medium confidence tier at 0.55 boundary
# ═══════════════════════════════════════════════════════════════════════════════

def test_model_predictor_medium_tier_at_boundary():
    """probability=0.55 must produce 'medium' confidence tier (inclusive boundary)."""
    import numpy as np

    features = {name: 0.5 for name in FEATURE_NAMES}
    model    = MagicMock()
    model.predict_proba.return_value = np.array([[0.45, 0.55]])
    model.feature_importances_       = np.ones(50)

    manager = MagicMock(spec=ModelManager)
    manager.get_model.return_value          = model
    manager.get_active_version.return_value = {
        "id": 3, "model_path": "models/v3.pkl",
        "oos_sharpe": 0.9, "oos_win_rate": 0.55, "trained_at": "2024-03-01",
    }

    predictor = ModelPredictor(manager=manager)
    result    = predictor.predict(features)

    assert result["confidence_tier"] == "medium", (
        f"prob=0.55 must be 'medium', got '{result['confidence_tier']}'"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 23 — Model trainer: saves model file to disk
# ═══════════════════════════════════════════════════════════════════════════════

def test_model_trainer_saves_model_file():
    """WalkForwardTrainer.run() must save a .pkl file to models_dir."""
    import tempfile, os
    tmpdir  = tempfile.mkdtemp()
    trainer = WalkForwardTrainer(models_dir=tmpdir)

    with _sync_db_ctx(fetchall_val=_feature_rows(60), fetchone_val=(1,)):
        result = trainer.run()

    assert os.path.exists(result["model_path"]), (
        f"Model file not found at {result['model_path']}"
    )
    assert result["model_path"].endswith(".pkl")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 24 — Feature engineer: regime_volatile flag
# ═══════════════════════════════════════════════════════════════════════════════

def test_feature_engineer_regime_volatile_flag():
    """When regime is 'volatile', regime_volatile=1.0 and others=0.0."""
    ctx = _signal_context()
    ctx["regime_info"]["regime"] = "volatile"

    features = FeatureEngineer().extract(ctx)

    assert features["regime_volatile"] == 1.0
    assert features["regime_trending"] == 0.0
    assert features["regime_ranging"]  == 0.0
