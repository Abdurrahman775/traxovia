"""
tests/test_phase2.py — Phase 2 quality gate tests.

All tests run without a live bridge or database. Windows-only imports
(MetaTrader5) and Phase 7 imports (notifications.telegram_handler) are
stubbed in sys.modules before any project code is imported.

Tests 1–3 verify Phase 2 module behaviour through mocking.
Tests 4–5 verify static constants and control-flow logic.
"""

import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

# ── Stub Windows-only and not-yet-built imports ────────────────────────────────
# Must happen before any project module import that transitively pulls them in.

_mt5_stub = MagicMock()
_mt5_stub.initialize.return_value     = True
_mt5_stub.login.return_value          = True
_mt5_stub.shutdown.return_value       = None
_mt5_stub.TRADE_RETCODE_DONE          = 10009
_mt5_stub.TRADE_ACTION_DEAL           = 1
_mt5_stub.ORDER_TYPE_BUY              = 0
_mt5_stub.ORDER_TYPE_SELL             = 1
_mt5_stub.ORDER_TIME_GTC              = 1
_mt5_stub.ORDER_FILLING_IOC           = 1

_mt5_account = MagicMock()
_mt5_account.login   = 123456
_mt5_account.server  = "Exness-MT5Test"
_mt5_account.balance = 10_000.0
_mt5_account.equity  = 10_000.0
_mt5_stub.account_info.return_value = _mt5_account

for _tf in ["M1","M5","M15","M30","H1","H4","D1","W1","MN1"]:
    setattr(_mt5_stub, f"TIMEFRAME_{_tf}", MagicMock())

sys.modules["MetaTrader5"]                    = _mt5_stub
sys.modules["notifications"]                  = MagicMock()
sys.modules["notifications.telegram_handler"] = MagicMock()

# ── Now safe to import project modules ────────────────────────────────────────

import asyncio

import httpx
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()

import core.execution_engine.mt5_bridge as _bridge
from core.risk_engine.spread_filter import check_spread
from data_engine.historical_loader import LOAD_PLAN, W1_MIN_BARS
from data_engine.realtime_feed import (
    PAIRS,
    _is_monday_utc,
    run_realtime_update,
)

# ── Lifespan helpers ──────────────────────────────────────────────────────────
# Patch _mt5_init/_mt5_shutdown so TestClient's lifespan doesn't touch the
# real MT5 mock state and doesn't reset _mt5_connected on teardown.

def _fake_init() -> bool:
    _bridge._mt5_connected = True
    return True

def _fake_shutdown() -> None:
    pass   # don't flip _mt5_connected back to False between tests


# ══════════════════════════════════════════════════════════════════════════════
# Test 1 — /health response shape: primary and standby
# ══════════════════════════════════════════════════════════════════════════════

def test_primary_bridge_health_shape():
    """
    GET /health on the primary bridge returns status, mt5_connected, and
    is_standby=False with a valid API key.
    """
    _bridge._API_KEY  = "test-key-phase2"
    _bridge.IS_STANDBY = False

    with (
        patch.object(_bridge, "_mt5_init",    side_effect=_fake_init),
        patch.object(_bridge, "_mt5_shutdown", side_effect=_fake_shutdown),
        TestClient(_bridge.app, raise_server_exceptions=True) as client,
    ):
        resp = client.get("/health", headers={"X-Api-Key": "test-key-phase2"})

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    for field in ("status", "mt5_connected", "is_standby"):
        assert field in data, f"/health response missing field '{field}'"

    assert data["mt5_connected"] is True,  "mt5_connected should be True"
    assert data["is_standby"]   is False,  "primary bridge: is_standby must be False"
    assert data["status"]       == "ok",   f"expected status='ok', got {data['status']!r}"


def test_standby_bridge_health_is_standby_true():
    """
    When IS_STANDBY=True (standby VPS), /health returns is_standby=True.
    All other fields retain the same shape.
    """
    _bridge._API_KEY  = "test-key-phase2"
    original_standby  = _bridge.IS_STANDBY
    _bridge.IS_STANDBY = True

    try:
        with (
            patch.object(_bridge, "_mt5_init",    side_effect=_fake_init),
            patch.object(_bridge, "_mt5_shutdown", side_effect=_fake_shutdown),
            TestClient(_bridge.app, raise_server_exceptions=True) as client,
        ):
            resp = client.get("/health", headers={"X-Api-Key": "test-key-phase2"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_standby"] is True,  "standby bridge: is_standby must be True"
        assert data["mt5_connected"] is True
        assert data["status"] == "ok"

    finally:
        _bridge.IS_STANDBY = original_standby


def test_health_rejects_wrong_api_key():
    """Requests with an incorrect X-Api-Key must be rejected with 403."""
    _bridge._API_KEY = "real-secret"

    with (
        patch.object(_bridge, "_mt5_init",    side_effect=_fake_init),
        patch.object(_bridge, "_mt5_shutdown", side_effect=_fake_shutdown),
        TestClient(_bridge.app, raise_server_exceptions=True) as client,
    ):
        resp = client.get("/health", headers={"X-Api-Key": "wrong-key"})

    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# Test 2 — Spread filter: blocks wide spread, allows normal spread
# ══════════════════════════════════════════════════════════════════════════════

def _mock_spread_client(spread_pips: float):
    """Return a patch context that makes httpx return the given spread."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "symbol":        "EURUSD",
        "spread_pips":   spread_pips,
        "spread_points": spread_pips * 10,
        "bid":           1.10000,
        "ask":           1.10000 + spread_pips * 0.0001,
        "timestamp":     "2026-04-25T12:00:00+00:00",
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    class _CM:
        async def __aenter__(self): return mock_client
        async def __aexit__(self, *_): pass

    return patch("core.risk_engine.spread_filter.httpx.AsyncClient", return_value=_CM())


def test_spread_filter_blocks_wide_spread():
    """
    EURUSD spread 2.0 pips > threshold 1.5 pips (1.0 × 1.5) → allowed=False.
    """
    from core.execution_engine.bridge_watchdog import bridge_state
    bridge_state["active_url"] = "http://fake-bridge:8001"

    with _mock_spread_client(spread_pips=2.0):
        result = asyncio.run(check_spread("EURUSD"))

    assert result["allowed"]        is False,  "wide spread must block the signal"
    assert result["symbol"]         == "EURUSD"
    assert result["current_spread"] == 2.0
    assert result["baseline"]       == 1.0,    "EURUSD baseline is 1.0 pip"
    assert result["threshold"]      == 1.5,    "threshold = baseline × 1.5"
    assert "1.5" in result["reason"] or "2.0" in result["reason"]


def test_spread_filter_allows_normal_spread():
    """
    EURUSD spread 1.0 pip ≤ threshold 1.5 pips → allowed=True.
    """
    from core.execution_engine.bridge_watchdog import bridge_state
    bridge_state["active_url"] = "http://fake-bridge:8001"

    with _mock_spread_client(spread_pips=1.0):
        result = asyncio.run(check_spread("EURUSD"))

    assert result["allowed"]        is True,  "normal spread must allow the signal"
    assert result["current_spread"] == 1.0
    assert result["threshold"]      == 1.5


def test_spread_filter_allows_spread_at_exact_threshold():
    """Spread exactly at threshold (1.5 pips) must still be allowed (not strictly >)."""
    from core.execution_engine.bridge_watchdog import bridge_state
    bridge_state["active_url"] = "http://fake-bridge:8001"

    with _mock_spread_client(spread_pips=1.5):
        result = asyncio.run(check_spread("EURUSD"))

    assert result["allowed"] is True, "spread equal to threshold must be allowed"


# ══════════════════════════════════════════════════════════════════════════════
# Test 3 — Spread filter fails safe when bridge is unreachable
# ══════════════════════════════════════════════════════════════════════════════

def test_spread_filter_fails_safe_on_timeout():
    """
    httpx.TimeoutException → allowed=False, current_spread=None.
    A slow bridge is itself a risk signal — block the trade.
    """
    from core.execution_engine.bridge_watchdog import bridge_state
    bridge_state["active_url"] = "http://fake-bridge:8001"

    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.TimeoutException("connection timed out")

    class _CM:
        async def __aenter__(self): return mock_client
        async def __aexit__(self, *_): pass

    with patch("core.risk_engine.spread_filter.httpx.AsyncClient", return_value=_CM()):
        result = asyncio.run(check_spread("EURUSD"))

    assert result["allowed"]        is False
    assert result["current_spread"] is None
    assert "timeout" in result["reason"].lower()


def test_spread_filter_fails_safe_on_http_error():
    """Bridge HTTP 503 → allowed=False (bridge degraded counts as unreachable)."""
    from core.execution_engine.bridge_watchdog import bridge_state
    bridge_state["active_url"] = "http://fake-bridge:8001"

    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503", request=MagicMock(), response=mock_resp
    )

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    class _CM:
        async def __aenter__(self): return mock_client
        async def __aexit__(self, *_): pass

    with patch("core.risk_engine.spread_filter.httpx.AsyncClient", return_value=_CM()):
        result = asyncio.run(check_spread("EURUSD"))

    assert result["allowed"]        is False
    assert result["current_spread"] is None


def test_spread_filter_fails_safe_when_no_bridge_url():
    """bridge_state active_url missing → allowed=False, not an exception."""
    from core.execution_engine.bridge_watchdog import bridge_state
    original = bridge_state.get("active_url")
    bridge_state["active_url"] = ""

    try:
        result = asyncio.run(check_spread("EURUSD"))
    finally:
        bridge_state["active_url"] = original

    assert result["allowed"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Test 4 — historical_loader LOAD_PLAN constants
# ══════════════════════════════════════════════════════════════════════════════

def test_historical_loader_load_plan_bar_counts():
    """
    M15 ≥ 8640 bars (≈ 3 months), H4 ≥ 1500 bars (≈ 1 year),
    W1 ≥ 52 bars (weekly_analyzer minimum). No DB or bridge needed.
    """
    by_tf = {entry["timeframe"]: entry for entry in LOAD_PLAN}

    assert set(by_tf) >= {"M15", "H4", "W1"}, \
        f"LOAD_PLAN missing timeframes. Found: {set(by_tf)}"

    assert by_tf["M15"]["count"] >= 8640, \
        f"M15 count {by_tf['M15']['count']} < 8640 (≈ 3 months)"
    assert by_tf["H4"]["count"]  >= 1500, \
        f"H4 count {by_tf['H4']['count']} < 1500 (≈ 1 year)"
    assert by_tf["W1"]["count"]  >= W1_MIN_BARS, \
        f"W1 count {by_tf['W1']['count']} < W1_MIN_BARS ({W1_MIN_BARS})"


def test_historical_loader_w1_has_no_spread():
    """
    ohlc_w1 schema has no spread column — LOAD_PLAN must reflect this.
    A wrong has_spread=True would cause an INSERT column mismatch at runtime.
    """
    by_tf = {entry["timeframe"]: entry for entry in LOAD_PLAN}

    assert by_tf["W1"]["has_spread"] is False, \
        "W1 has_spread must be False — ohlc_w1 table has no spread column"
    assert by_tf["M15"]["has_spread"] is True
    assert by_tf["H4"]["has_spread"]  is True


def test_historical_loader_covers_all_five_pairs():
    """PAIRS list in realtime_feed (shared source of truth) has all 5 symbols."""
    required = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"}
    assert required == set(PAIRS), \
        f"PAIRS mismatch. Expected {required}, got {set(PAIRS)}"


# ══════════════════════════════════════════════════════════════════════════════
# Test 5 — realtime_feed W1 Monday gate
# ══════════════════════════════════════════════════════════════════════════════

@contextmanager
def _mock_sync_db():
    """Minimal psycopg2 connection mock for Celery task tests."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 0                        # all bars → skipped (ON CONFLICT)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
    yield mock_conn


def test_realtime_feed_skips_w1_on_non_monday():
    """
    On a non-Monday, W1 must not appear in any bridge fetch call.
    M15 and H4 must always be fetched.
    """
    fetched: set[str] = set()

    def _spy_fetch(symbol, timeframe, count):
        fetched.add(timeframe)
        return []   # empty → _upsert_bars returns (0,0) immediately

    with (
        patch("data_engine.realtime_feed._BRIDGE_URL",    "http://fake-bridge:8001"),
        patch("data_engine.realtime_feed._API_KEY",       "test-key"),
        patch("data_engine.realtime_feed._is_monday_utc", return_value=False),
        patch("data_engine.realtime_feed._fetch_bars",    side_effect=_spy_fetch),
        patch("data_engine.realtime_feed.get_sync_db",    _mock_sync_db),
    ):
        run_realtime_update()

    assert "W1"  not in fetched, f"W1 was fetched on a non-Monday (fetched={fetched})"
    assert "M15" in fetched,     "M15 must always be fetched"
    assert "H4"  in fetched,     "H4 must always be fetched"


def test_realtime_feed_includes_w1_on_monday():
    """On Monday, W1 must be fetched alongside M15 and H4."""
    fetched: set[str] = set()

    def _spy_fetch(symbol, timeframe, count):
        fetched.add(timeframe)
        return []

    with (
        patch("data_engine.realtime_feed._BRIDGE_URL",    "http://fake-bridge:8001"),
        patch("data_engine.realtime_feed._API_KEY",       "test-key"),
        patch("data_engine.realtime_feed._is_monday_utc", return_value=True),
        patch("data_engine.realtime_feed._fetch_bars",    side_effect=_spy_fetch),
        patch("data_engine.realtime_feed.get_sync_db",    _mock_sync_db),
    ):
        run_realtime_update()

    assert "W1"  in fetched, "W1 must be fetched on Monday"
    assert "M15" in fetched
    assert "H4"  in fetched


def test_realtime_feed_fetches_all_five_pairs():
    """Every run must request data for all 5 pairs for each active timeframe."""
    fetched_pairs: set[str] = set()

    def _spy_fetch(symbol, timeframe, count):
        fetched_pairs.add(symbol)
        return []

    with (
        patch("data_engine.realtime_feed._BRIDGE_URL",    "http://fake-bridge:8001"),
        patch("data_engine.realtime_feed._API_KEY",       "test-key"),
        patch("data_engine.realtime_feed._is_monday_utc", return_value=False),
        patch("data_engine.realtime_feed._fetch_bars",    side_effect=_spy_fetch),
        patch("data_engine.realtime_feed.get_sync_db",    _mock_sync_db),
    ):
        run_realtime_update()

    expected = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"}
    assert fetched_pairs == expected, \
        f"Expected pairs {expected}, fetched {fetched_pairs}"


def test_realtime_feed_uses_requests_not_httpx():
    """Verify realtime_feed imports requests (sync), not httpx (async)."""
    import data_engine.realtime_feed as feed_module
    import importlib
    assert hasattr(feed_module, "requests"), \
        "realtime_feed must import requests (sync) for use in Celery workers"
    assert not hasattr(feed_module, "httpx"), \
        "realtime_feed must not import httpx (async) — Celery workers are sync"


# ── Allow running directly ────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
