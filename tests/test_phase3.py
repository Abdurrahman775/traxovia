"""
tests/test_phase3.py — Phase 3 quality gate tests.

Tests 1–3 connect to the live TimescaleDB (requires DATABASE_URL in .env).
Tests 4–5 are pure unit tests with no I/O.

Run all:
    pytest tests/test_phase3.py -v

Run only unit tests (no DB):
    pytest tests/test_phase3.py -v -m "not db"
"""

import math
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pandas as pd
import pytest
import pytest_asyncio
from dotenv import load_dotenv

load_dotenv()

from config import settings
from core.risk_engine.position_sizer import calculate_lot_size
from core.structure_engine.bos_identifier import BOSIdentifier
from core.structure_engine.regime_classifier import RegimeClassifier
from core.structure_engine.weekly_analyzer import WeeklyAnalyzer


# ── DB fixture ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_conn():
    """
    Per-test asyncpg connection.  Function scope ensures each async test gets
    a connection created in its own event loop — module scope causes asyncpg
    to attach the connection's Future to the module-creation loop which is
    different from the per-test loop pytest-asyncio spins up.

    Skips the test if DATABASE_URL is not set or DB is unreachable.
    """
    if not settings.database_url:
        pytest.skip("DATABASE_URL not configured — skipping DB tests")

    try:
        conn = await asyncpg.connect(settings.database_url, timeout=5)
    except Exception as exc:
        pytest.skip(f"Cannot connect to TimescaleDB: {exc}")

    yield conn
    await conn.close()


def _rows_to_df(rows: list) -> pd.DataFrame:
    """Convert asyncpg rows to a OHLC DataFrame."""
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    df["time"] = pd.to_datetime(df["time"])
    return df


# ── Test 1: RegimeClassifier on real H4 data ──────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.db
async def test_regime_classifier_on_real_h4_data(db_conn):
    """
    Fetch 100 real H4 bars for EURUSD and verify RegimeClassifier returns
    a well-formed result with no NaN values.
    """
    rows = await db_conn.fetch(
        """
        SELECT time, open, high, low, close
        FROM   ohlc_h4
        WHERE  symbol = 'EURUSD'
        ORDER  BY time DESC
        LIMIT  100
        """,
    )
    assert len(rows) >= 15, (
        f"Need at least 15 H4 bars for ADX computation, got {len(rows)}"
    )

    df = _rows_to_df(list(reversed(rows)))   # oldest first
    rc = RegimeClassifier()
    result = rc.classify(df)

    # Required keys present.
    for key in ("regime", "adx", "atr_ratio", "signal_gate"):
        assert key in result, f"Missing key '{key}' in classify() result"

    # Regime is one of the three valid values.
    assert result["regime"] in ("trending", "ranging", "volatile"), (
        f"Unexpected regime value: {result['regime']!r}"
    )

    # Signal gate matches regime.
    expected_gate = {
        "trending": "open",
        "ranging":  "blocked",
        "volatile": "reduced",
    }[result["regime"]]
    assert result["signal_gate"] == expected_gate, (
        f"signal_gate {result['signal_gate']!r} does not match "
        f"regime {result['regime']!r} (expected {expected_gate!r})"
    )

    # ADX and atr_ratio must be finite numbers (no NaN, no ±Inf).
    assert math.isfinite(result["adx"]), f"adx is not finite: {result['adx']}"
    assert math.isfinite(result["atr_ratio"]), (
        f"atr_ratio is not finite: {result['atr_ratio']}"
    )
    assert result["adx"] >= 0, f"adx must be non-negative, got {result['adx']}"
    assert result["atr_ratio"] >= 0, (
        f"atr_ratio must be non-negative, got {result['atr_ratio']}"
    )


# ── Test 2: WeeklyAnalyzer returns a bias from real W1 data ───────────────────

@pytest.mark.asyncio
@pytest.mark.db
async def test_weekly_analyzer_returns_bias(db_conn):
    """
    WeeklyAnalyzer must return 'bullish', 'bearish', or None — never raise.
    Redis is unavailable in CI so the test exercises the DB-fallback path by
    injecting a Redis mock whose .get() always raises ConnectionError.
    """
    mock_redis       = AsyncMock()
    mock_redis.get   = AsyncMock(side_effect=ConnectionError("no Redis in test"))
    mock_redis.set   = AsyncMock(side_effect=ConnectionError("no Redis in test"))
    mock_redis.aclose = AsyncMock()

    # Build a pool-like object that hands out the existing connection.
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        return_value=_AcquireContext(db_conn)
    )

    analyzer = WeeklyAnalyzer(pool=mock_pool, redis=mock_redis)
    bias = await analyzer.get_bias("EURUSD")

    assert bias in ("bullish", "bearish", None), (
        f"get_bias() returned unexpected value: {bias!r}"
    )


class _AcquireContext:
    """Async context manager that yields the given connection."""
    def __init__(self, conn): self._conn = conn
    async def __aenter__(self): return self._conn
    async def __aexit__(self, *_): pass


# ── Test 3: BOSIdentifier finds at least one BOS in real H4 data ──────────────

@pytest.mark.asyncio
@pytest.mark.db
async def test_bos_identifier_finds_bos_in_real_h4_data(db_conn):
    """
    Fetch 200 real H4 bars for EURUSD and verify at least one BOS event
    (bullish or bearish) is detected.  200 bars ≈ 33 days of H4 structure —
    sufficient to contain at least one confirmed swing high or low.
    """
    rows = await db_conn.fetch(
        """
        SELECT time, open, high, low, close
        FROM   ohlc_h4
        WHERE  symbol = 'EURUSD'
        ORDER  BY time DESC
        LIMIT  200
        """,
    )
    assert len(rows) >= 7, f"Need at least 7 bars, got {len(rows)}"

    df  = _rows_to_df(list(reversed(rows)))
    bos = BOSIdentifier(n=3)
    out = bos.identify(df)

    assert "bullish_bos" in out.columns, "bullish_bos column missing"
    assert "bearish_bos" in out.columns, "bearish_bos column missing"

    total_bos = int(out["bullish_bos"].sum() + out["bearish_bos"].sum())
    assert total_bos >= 1, (
        f"Expected at least 1 BOS event in 200 H4 bars, found {total_bos}. "
        "Check that DB data contains normal price movement."
    )


# ── Test 4: Position sizer — volatile regime with stage 1 DD ──────────────────

@pytest.mark.parametrize("regime,stage,expected_lot", [
    # volatile (0.5×) with stage 1 cap (0.5% max risk):
    # base = (10_000 * 0.015) / (20 * 10) = 150/200 = 0.75
    # after volatile: 0.75 * 0.5 = 0.375 → floor → 0.37
    # cap  = (10_000 * 0.005) / (20 * 10) = 50/200 = 0.25
    # result = min(0.37, 0.25) = 0.25
    ("volatile", 1, 0.25),
    # trending (1.0×) with stage 1 cap:
    # base = 0.75, cap = 0.25 → result = 0.25
    ("trending", 1, 0.25),
])
def test_position_sizer_volatile_stage1(regime, stage, expected_lot):
    """
    Stage 1 cap (0.5% max risk) is applied after the regime multiplier.
    Both volatile and trending are capped to the same lot when the uncapped
    lot exceeds the cap — confirming the cap is the binding constraint.
    """
    lot = calculate_lot_size(
        account_balance=10_000,
        risk_pct=0.015,      # 1.5% — above the 0.5% stage-1 cap
        sl_pips=20,
        symbol="EURUSD",
        regime=regime,
        dd_stage=stage,
    )
    assert lot > 0, f"Expected non-zero lot for {regime}/stage {stage}"
    assert lot == expected_lot, (
        f"regime={regime}, stage={stage}: expected {expected_lot}, got {lot}"
    )

    # Explicitly verify the stage-1 cap was binding: the uncapped lot would be
    # larger than the result, so the cap must have reduced it.
    uncapped = calculate_lot_size(
        account_balance=10_000,
        risk_pct=0.015,
        sl_pips=20,
        symbol="EURUSD",
        regime=regime,
        dd_stage=0,    # no cap
    )
    assert uncapped > lot or (
        regime == "volatile" and uncapped == lot
    ), (
        f"Stage {stage} should cap the lot below the uncapped value. "
        f"uncapped={uncapped}, capped={lot}"
    )


def test_position_sizer_volatile_multiplier_visible():
    """
    In stage 0 (no DD cap) volatile produces exactly half the trending lot,
    confirming the 0.5× multiplier is applied before any cap.
    """
    trending_lot = calculate_lot_size(10_000, 0.01, 20, "EURUSD", "trending", 0)
    volatile_lot = calculate_lot_size(10_000, 0.01, 20, "EURUSD", "volatile", 0)
    assert volatile_lot == trending_lot / 2, (
        f"volatile should be exactly half of trending: "
        f"trending={trending_lot}, volatile={volatile_lot}"
    )


# ── Test 5: Full regime gate integration ──────────────────────────────────────

def test_regime_gate_ranging_blocked():
    """
    Mocked ranging market (ADX=15 < 20 threshold, atr_ratio small):
    RegimeClassifier must return signal_gate='blocked' and regime='ranging'.
    """
    rc = RegimeClassifier()
    n  = 60
    # Sine-wave oscillation to give non-trivial inputs to _calc_atr.
    import math as _math
    closes = [1.0850 + 0.01 * _math.sin(2 * _math.pi * i / 8) for i in range(n)]
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  closes,
        "high":  [c + 0.001 for c in closes],
        "low":   [c - 0.001 for c in closes],
        "close": closes,
    })

    with patch.object(rc, "_calc_adx", return_value=15.0), \
         patch.object(rc, "_calc_atr", return_value=0.0001):
        result = rc.classify(df)

    assert result["regime"]      == "ranging",  f"Expected ranging, got {result['regime']!r}"
    assert result["signal_gate"] == "blocked",  f"Expected blocked, got {result['signal_gate']!r}"
    assert result["adx"]         == 15.0


def test_regime_gate_volatile_reduced():
    """
    Mocked volatile market (ATR ratio=2.5 > 2.0 threshold):
    RegimeClassifier must return regime='volatile' and signal_gate='reduced',
    regardless of ADX value (volatile check runs first).
    """
    rc = RegimeClassifier()
    n  = 60
    closes = [1.0850] * n
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  closes,
        "high":  [c + 0.050 for c in closes],
        "low":   [c - 0.050 for c in closes],
        "close": closes,
    })

    with patch.object(rc, "_calc_adx", return_value=30.0), \
         patch.object(rc, "_calc_atr", return_value=0.050):
        # pct_change().rolling(20).std() ≈ 0 on flat close → atr_ratio → ∞ → volatile
        result = rc.classify(df)

    assert result["regime"]      == "volatile", f"Expected volatile, got {result['regime']!r}"
    assert result["signal_gate"] == "reduced",  f"Expected reduced, got {result['signal_gate']!r}"
    assert result["atr_ratio"]   >  2.0,        f"atr_ratio should exceed 2.0, got {result['atr_ratio']}"


# ── Test 6: BOSIdentifier — no BOS on flat data ────────────────────────────────

def test_bos_identifier_no_bos_on_flat_data():
    """
    Perfectly flat OHLC data has no swing highs or lows, so BOSIdentifier
    must return zero BOS events.
    """
    n  = 50
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  [1.0850] * n,
        "high":  [1.0860] * n,
        "low":   [1.0840] * n,
        "close": [1.0850] * n,
    })
    bos = BOSIdentifier(n=3)
    out = bos.identify(df)

    assert "bullish_bos" in out.columns
    assert "bearish_bos" in out.columns
    assert int(out["bullish_bos"].sum()) == 0, "Flat data must have no bullish BOS"
    assert int(out["bearish_bos"].sum()) == 0, "Flat data must have no bearish BOS"


# ── Test 7: BOSIdentifier — bullish BOS on uptrend ────────────────────────────

def test_bos_identifier_bullish_bos_on_uptrend():
    """
    A zigzag uptrend (higher highs, higher lows) with confirmed swing highs
    must produce at least one bullish BOS.
    The pattern: rise → pullback → rise above previous high (BOS).
    """
    import numpy as np
    # Build explicit swing structure: swing high at 1.0900, then pullback,
    # then close above 1.0900 → bullish BOS
    n = 30
    # Bars 0-9: rise to swing high
    # Bars 10-16: pullback (n=3 bars after bar 9 confirms swing high at bar 9)
    # Bars 17-29: rise above swing high → BOS
    close = (
        list(np.linspace(1.0850, 1.0900, 10)) +   # rise
        list(np.linspace(1.0900, 1.0870, 7))  +   # pullback
        list(np.linspace(1.0870, 1.0950, 13))      # break above
    )
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  close,
        "high":  [c + 0.0002 for c in close],
        "low":   [c - 0.0002 for c in close],
        "close": close,
    })
    bos = BOSIdentifier(n=3)
    out = bos.identify(df)

    assert int(out["bullish_bos"].sum()) >= 1, (
        "Zigzag uptrend must produce at least one bullish BOS"
    )


# ── Test 8: BOSIdentifier — bearish BOS on downtrend ─────────────────────────

def test_bos_identifier_bearish_bos_on_downtrend():
    """
    A zigzag downtrend (lower highs, lower lows) must produce at least one
    bearish BOS.
    """
    import numpy as np
    n = 30
    # Bars 0-9: fall to swing low
    # Bars 10-16: bounce (n=3 bars after bar 9 confirms swing low at bar 9)
    # Bars 17-29: fall below swing low → BOS
    close = (
        list(np.linspace(1.1000, 1.0950, 10)) +   # fall
        list(np.linspace(1.0950, 1.0980, 7))  +   # bounce
        list(np.linspace(1.0980, 1.0900, 13))      # break below
    )
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  close,
        "high":  [c + 0.0002 for c in close],
        "low":   [c - 0.0002 for c in close],
        "close": close,
    })
    bos = BOSIdentifier(n=3)
    out = bos.identify(df)

    assert int(out["bearish_bos"].sum()) >= 1, (
        "Zigzag downtrend must produce at least one bearish BOS"
    )


# ── Test 9: BOSIdentifier — output has same length as input ───────────────────

def test_bos_identifier_output_length_matches_input():
    """identify() must return a DataFrame with the same number of rows as input."""
    import numpy as np
    rng    = np.random.default_rng(7)
    n      = 100
    close  = 1.0850 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  close,
        "high":  close + 0.0005,
        "low":   close - 0.0005,
        "close": close,
    })
    bos = BOSIdentifier(n=3)
    out = bos.identify(df)

    assert len(out) == n, f"Output length {len(out)} != input length {n}"


# ── Test 10: RegimeClassifier — trending regime ────────────────────────────────

def test_regime_classifier_trending():
    """
    Mocked trending market (ADX=30 > 20, atr_ratio < 2.0):
    RegimeClassifier must return regime='trending' and signal_gate='open'.
    Both _calc_adx and _calc_atr are mocked; close data has real volatility
    so the atr_ratio calculation uses the mocked ATR value correctly.
    """
    import numpy as np
    rc  = RegimeClassifier()
    rng = np.random.default_rng(1)
    n   = 60
    # Non-flat close so pct_change().rolling(20).std() > 0
    close = 1.0850 + np.cumsum(rng.normal(0, 0.001, n))
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  close,
        "high":  close + 0.0005,
        "low":   close - 0.0005,
        "close": close,
    })

    with patch.object(rc, "_calc_adx", return_value=30.0), \
         patch.object(rc, "_calc_atr", return_value=0.0005):
        result = rc.classify(df)

    assert result["regime"]      == "trending", f"Expected trending, got {result['regime']!r}"
    assert result["signal_gate"] == "open",     f"Expected open, got {result['signal_gate']!r}"
    assert result["adx"]         == 30.0


# ── Test 11: RegimeClassifier — result keys always present ────────────────────

def test_regime_classifier_result_has_required_keys():
    """classify() must always return all four required keys."""
    import numpy as np
    rc  = RegimeClassifier()
    rng = np.random.default_rng(2)
    n   = 30
    close = 1.0850 + np.cumsum(rng.normal(0, 0.001, n))
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  close,
        "high":  close + 0.001,
        "low":   close - 0.001,
        "close": close,
    })
    result = rc.classify(df)

    for key in ("regime", "adx", "atr_ratio", "signal_gate"):
        assert key in result, f"Missing key '{key}' in classify() result"


# ── Test 12: RegimeClassifier — ADX threshold boundary ────────────────────────

@pytest.mark.parametrize("adx,expected_regime", [
    (19.9, "ranging"),
    (20.0, "trending"),
    (25.0, "trending"),
])
def test_regime_classifier_adx_boundary(adx, expected_regime):
    """ADX threshold is exactly 20.0: below → ranging, at/above → trending."""
    import numpy as np
    rc  = RegimeClassifier()
    rng = np.random.default_rng(3)
    n   = 30
    close = 1.0850 + np.cumsum(rng.normal(0, 0.001, n))
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  close,
        "high":  close + 0.0005,
        "low":   close - 0.0005,
        "close": close,
    })

    with patch.object(rc, "_calc_adx", return_value=adx), \
         patch.object(rc, "_calc_atr", return_value=0.0005):
        result = rc.classify(df)

    assert result["regime"] == expected_regime, (
        f"ADX={adx}: expected '{expected_regime}', got '{result['regime']}'"
    )


# ── Test 13: ZoneDetector — check_gate returns required keys ──────────────────

def test_zone_detector_check_gate_returns_required_keys():
    """ZoneDetector.check_gate() must return a dict with 'passed', 'zone', 'reason'."""
    from core.structure_engine.zone_detector import ZoneDetector
    import numpy as np

    rng   = np.random.default_rng(5)
    n     = 50
    close = 1.0850 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="15min"),
        "open":  close,
        "high":  close + 0.0005,
        "low":   close - 0.0005,
        "close": close,
    })

    zd     = ZoneDetector()
    result = zd.check_gate(df, "bullish")

    for key in ("passed", "zone", "reason"):
        assert key in result, f"Missing key '{key}' in check_gate() result"
    assert isinstance(result["passed"], bool)
    assert isinstance(result["reason"], str)


# ── Test 14: Zone dataclass — fields accessible ───────────────────────────────

def test_zone_dataclass_fields():
    """Zone dataclass must expose all required fields."""
    from core.structure_engine.zone_detector import Zone

    zone = Zone(
        zone_type="demand",
        top=1.0860,
        bottom=1.0840,
        strength=80.0,
        test_count=2,
        origin_index=10,
        created_at=pd.Timestamp("2024-01-01"),
    )

    assert zone.zone_type    == "demand"
    assert zone.top          == pytest.approx(1.0860)
    assert zone.bottom       == pytest.approx(1.0840)
    assert zone.strength     == pytest.approx(80.0)
    assert zone.test_count   == 2
    assert zone.origin_index == 10


# ── Test 15: WeeklyAnalyzer — returns None when no pool/redis ─────────────────

@pytest.mark.asyncio
async def test_weekly_analyzer_returns_none_without_data():
    """WeeklyAnalyzer with no pool and no redis must return None without raising."""
    analyzer = WeeklyAnalyzer(pool=None, redis=None)
    bias = await analyzer.get_bias("GBPUSD")
    assert bias is None, f"Expected None without data sources, got {bias!r}"


# ── Test 16: WeeklyAnalyzer — redis cache hit ─────────────────────────────────

@pytest.mark.asyncio
async def test_weekly_analyzer_uses_redis_cache():
    """WeeklyAnalyzer must return cached value from Redis without hitting DB."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=b"bullish")

    analyzer = WeeklyAnalyzer(pool=None, redis=mock_redis)
    bias = await analyzer.get_bias("EURUSD")

    assert bias == "bullish", f"Expected 'bullish' from cache, got {bias!r}"
    mock_redis.get.assert_awaited_once()


# ── Test 17: Position sizer — stage 3 returns zero ────────────────────────────

def test_position_sizer_stage3_returns_zero():
    """Stage 3 drawdown must return lot_size=0.0 regardless of other params."""
    lot = calculate_lot_size(
        account_balance=50_000,
        risk_pct=0.02,
        sl_pips=20,
        symbol="EURUSD",
        regime="trending",
        dd_stage=3,
    )
    assert lot == 0.0, f"Stage 3 must return 0.0, got {lot}"


# ── Test 18: Position sizer — JPY pair uses 1000 pip value ────────────────────

def test_position_sizer_jpy_pair():
    """JPY pairs use pip_value=1000 per lot (not 10)."""
    lot_eur = calculate_lot_size(10_000, 0.01, 20, "EURUSD", "trending", 0)
    lot_jpy = calculate_lot_size(10_000, 0.01, 20, "USDJPY", "trending", 0)

    assert lot_jpy < lot_eur, (
        f"JPY pair should produce smaller lot due to higher pip value: "
        f"EURUSD={lot_eur}, USDJPY={lot_jpy}"
    )


# ── Test 19: Position sizer — minimum lot floor ───────────────────────────────

def test_position_sizer_minimum_lot_floor():
    """calculate_lot_size must never return less than 0.01 (minimum lot)."""
    # Very small balance + large SL → would compute < 0.01 without floor
    lot = calculate_lot_size(
        account_balance=100,
        risk_pct=0.001,
        sl_pips=500,
        symbol="EURUSD",
        regime="trending",
        dd_stage=0,
    )
    assert lot >= 0.01, f"Lot must be at least 0.01, got {lot}"


# ── Test 20: RegimeClassifier — ADX is non-negative ───────────────────────────

def test_regime_classifier_adx_non_negative():
    """ADX must always be >= 0 regardless of input data."""
    import numpy as np
    rc  = RegimeClassifier()
    rng = np.random.default_rng(99)
    n   = 50
    close = 1.0850 + np.cumsum(rng.normal(0, 0.001, n))
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  close,
        "high":  close + 0.0005,
        "low":   close - 0.0005,
        "close": close,
    })
    result = rc.classify(df)
    assert result["adx"] >= 0, f"ADX must be non-negative, got {result['adx']}"


# ── Test 21: RegimeClassifier — atr_ratio is non-negative ─────────────────────

def test_regime_classifier_atr_ratio_non_negative():
    """atr_ratio must always be >= 0."""
    import numpy as np
    rc  = RegimeClassifier()
    rng = np.random.default_rng(88)
    n   = 50
    close = 1.0850 + np.cumsum(rng.normal(0, 0.001, n))
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  close,
        "high":  close + 0.0005,
        "low":   close - 0.0005,
        "close": close,
    })
    result = rc.classify(df)
    assert result["atr_ratio"] >= 0, f"atr_ratio must be non-negative, got {result['atr_ratio']}"


# ── Test 22: BOSIdentifier — n parameter affects swing detection ──────────────

def test_bos_identifier_n_parameter():
    """
    A larger n requires more bars to confirm a swing, so n=10 should detect
    fewer or equal BOS events than n=2 on the same data.
    """
    import numpy as np
    n = 30
    close = (
        list(np.linspace(1.0850, 1.0900, 10)) +
        list(np.linspace(1.0900, 1.0870, 7))  +
        list(np.linspace(1.0870, 1.0950, 13))
    )
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  close,
        "high":  [c + 0.0002 for c in close],
        "low":   [c - 0.0002 for c in close],
        "close": close,
    })

    bos_small = BOSIdentifier(n=2)
    bos_large = BOSIdentifier(n=10)

    out_small = bos_small.identify(df)
    out_large = bos_large.identify(df)

    total_small = int(out_small["bullish_bos"].sum() + out_small["bearish_bos"].sum())
    total_large = int(out_large["bullish_bos"].sum() + out_large["bearish_bos"].sum())

    assert total_large <= total_small, (
        f"Larger n should detect <= BOS events: n=2 found {total_small}, n=10 found {total_large}"
    )


# ── Test 23: Position sizer — stage 2 caps correctly ─────────────────────────

def test_position_sizer_stage2_cap():
    """Stage 2 caps risk at 0.25% — lot must equal 0.25%-risk baseline."""
    lot_stage2 = calculate_lot_size(10_000, 0.02, 100, "EURUSD", "trending", 2)
    lot_at_cap = calculate_lot_size(10_000, 0.0025, 100, "EURUSD", "trending", 0)

    assert lot_stage2 == pytest.approx(lot_at_cap), (
        f"Stage 2 lot {lot_stage2} must equal 0.25%-risk baseline {lot_at_cap}"
    )


# ── Test 24: WeeklyAnalyzer — redis returns invalid value falls back ──────────

@pytest.mark.asyncio
async def test_weekly_analyzer_redis_invalid_value_falls_back():
    """
    If Redis returns an invalid value (not 'bullish'/'bearish'), WeeklyAnalyzer
    must fall back to DB (or return None if no pool).
    """
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=b"invalid_value")

    analyzer = WeeklyAnalyzer(pool=None, redis=mock_redis)
    bias = await analyzer.get_bias("EURUSD")

    # With no pool, falls back to None
    assert bias is None, f"Invalid Redis value should fall back to None, got {bias!r}"


# ── Test 25: Position sizer — volatile + stage 2 combined ────────────────────

def test_position_sizer_volatile_stage2_combined():
    """
    Volatile (0.5×) + stage 2 cap (0.25%): the cap should be the binding constraint
    when the uncapped volatile lot exceeds the cap.
    """
    lot = calculate_lot_size(10_000, 0.02, 100, "EURUSD", "volatile", 2)
    cap_lot = calculate_lot_size(10_000, 0.0025, 100, "EURUSD", "trending", 0)

    assert lot == pytest.approx(cap_lot), (
        f"Volatile+stage2 lot {lot} must equal stage-2 cap baseline {cap_lot}"
    )


# ── Test 26: BOSIdentifier — identify preserves original columns ──────────────

def test_bos_identifier_preserves_original_columns():
    """identify() must preserve all original OHLC columns in the output."""
    import numpy as np
    n = 20
    close = 1.0850 + np.arange(n) * 0.0001
    df = pd.DataFrame({
        "time":  pd.date_range("2024-01-01", periods=n, freq="h"),
        "open":  close,
        "high":  close + 0.0005,
        "low":   close - 0.0005,
        "close": close,
    })
    bos = BOSIdentifier(n=3)
    out = bos.identify(df)

    for col in ("time", "open", "high", "low", "close"):
        assert col in out.columns, f"Column '{col}' missing from identify() output"
