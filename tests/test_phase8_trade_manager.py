"""
tests/test_phase8_trade_manager.py — Unit tests for trade_manager.py

Tests cover:
  - _sl_tp_hit():  buy/sell TP/SL detection, no-hit case
  - _compute_pnl(): pnl_r and pip calc for buy/sell, JPY pair
  - check_and_close_positions(): full mock cycle — spread fetch, bridge close,
    DB update, feedback_loop trigger; also covers no-hit (nothing closed)
    and bridge-close failure (broker-closed fallback)
"""

import asyncio
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# ── Pre-mock only the feedback_loop which imports telegram/notifications that
# are absent in unit-test context. database.sync_connection is a real module
# that imports cleanly without a live DB; it is patched per-test at call sites.
_TM_MOCKED = ("core.ai_engine", "core.ai_engine.feedback_loop")
_tm_pre_existing = {m for m in _TM_MOCKED if m in sys.modules}
for _mod in _TM_MOCKED:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from core.execution_engine.trade_manager import (
    _close_trade_in_db,
    _compute_pnl,
    _sl_tp_hit,
    check_and_close_positions,
)

# Remove mocks immediately after imports to avoid polluting later test files.
for _m in _TM_MOCKED:
    if _m not in _tm_pre_existing:
        sys.modules.pop(_m, None)


# ── _sl_tp_hit() ──────────────────────────────────────────────────────────────

class TestSlTpHit:

    def _trade(self, direction, sl, tp):
        return {"direction": direction, "stop_loss": sl, "take_profit": tp}

    # Buy hits
    def test_buy_tp_when_bid_reaches_tp(self):
        assert _sl_tp_hit(self._trade("buy", 1.080, 1.090), bid=1.090, ask=1.0901) == "tp"

    def test_buy_tp_when_bid_above_tp(self):
        assert _sl_tp_hit(self._trade("buy", 1.080, 1.090), bid=1.095, ask=1.096) == "tp"

    def test_buy_sl_when_bid_reaches_sl(self):
        assert _sl_tp_hit(self._trade("buy", 1.080, 1.090), bid=1.080, ask=1.0801) == "sl"

    def test_buy_sl_when_bid_below_sl(self):
        assert _sl_tp_hit(self._trade("buy", 1.080, 1.090), bid=1.075, ask=1.076) == "sl"

    def test_buy_no_hit_between_sl_and_tp(self):
        assert _sl_tp_hit(self._trade("buy", 1.080, 1.090), bid=1.085, ask=1.0851) is None

    # Sell hits
    def test_sell_tp_when_ask_reaches_tp(self):
        assert _sl_tp_hit(self._trade("sell", 1.095, 1.080), bid=1.0799, ask=1.080) == "tp"

    def test_sell_tp_when_ask_below_tp(self):
        assert _sl_tp_hit(self._trade("sell", 1.095, 1.080), bid=1.074, ask=1.075) == "tp"

    def test_sell_sl_when_ask_reaches_sl(self):
        assert _sl_tp_hit(self._trade("sell", 1.095, 1.080), bid=1.094, ask=1.095) == "sl"

    def test_sell_sl_when_ask_above_sl(self):
        assert _sl_tp_hit(self._trade("sell", 1.095, 1.080), bid=1.097, ask=1.098) == "sl"

    def test_sell_no_hit_between_tp_and_sl(self):
        assert _sl_tp_hit(self._trade("sell", 1.095, 1.080), bid=1.085, ask=1.0851) is None


# ── _compute_pnl() ─────────────────────────────────────────────────────────────

class TestComputePnl:

    def _trade(self, direction, entry, sl, pair="EURUSD"):
        return {
            "direction":   direction,
            "entry_price": entry,
            "stop_loss":   sl,
            "pair":        pair,
        }

    def test_buy_win_pnl_r(self):
        # entry=1.0850, sl=1.0820, close=1.0880 → move=0.0030, risk=0.0030 → pnl_r=1.0
        trade = self._trade("buy", 1.0850, 1.0820)
        pnl_r, pips = _compute_pnl(trade, 1.0880)
        assert pnl_r == pytest.approx(1.0, abs=0.001)
        assert pips  == pytest.approx(30.0, abs=0.2)

    def test_buy_loss_pnl_r_negative(self):
        trade = self._trade("buy", 1.0850, 1.0820)
        pnl_r, pips = _compute_pnl(trade, 1.0820)
        assert pnl_r < 0 or pnl_r == pytest.approx(-1.0, abs=0.001)
        assert pips  <= 0

    def test_sell_win_pnl_r(self):
        # entry=1.0850, sl=1.0880, close=1.0820 → move=0.0030, risk=0.0030 → pnl_r=1.0
        trade = self._trade("sell", 1.0850, 1.0880)
        pnl_r, pips = _compute_pnl(trade, 1.0820)
        assert pnl_r == pytest.approx(1.0, abs=0.001)
        assert pips  == pytest.approx(30.0, abs=0.2)

    def test_jpy_pair_uses_100_pip_multiplier(self):
        # USDJPY: 1 pip = 0.01, multiplier=100
        trade = self._trade("buy", 150.00, 149.50, pair="USDJPY")
        _, pips = _compute_pnl(trade, 150.50)
        assert pips == pytest.approx(50.0, abs=0.5)

    def test_xau_pair_uses_10_pip_multiplier(self):
        trade = self._trade("buy", 2340.0, 2330.0, pair="XAUUSD")
        _, pips = _compute_pnl(trade, 2350.0)
        assert pips == pytest.approx(100.0, abs=1.0)

    def test_zero_risk_returns_zero_pnl_r(self):
        # SL == entry → risk_per_unit = 0 → no division by zero
        trade = self._trade("buy", 1.085, 1.085)
        pnl_r, _ = _compute_pnl(trade, 1.090)
        assert pnl_r == 0.0


# ── check_and_close_positions() ───────────────────────────────────────────────

def _make_open_trade(**overrides):
    base = {
        "id":          "trade-uuid-1",
        "user_id":     "user-uuid-1",
        "pair":        "EURUSD",
        "direction":   "buy",
        "entry_price": 1.08500,
        "stop_loss":   1.08200,
        "take_profit": 1.08900,
        "lot_size":    0.01,
        "mt5_ticket":  12345678,
    }
    base.update(overrides)
    return base


def _spread(bid, ask, symbol="EURUSD"):
    return {
        "symbol":        symbol,
        "bid":           bid,
        "ask":           ask,
        "spread_pips":   1.0,
        "spread_points": 10.0,
        "timestamp":     "2026-04-30T00:00:00Z",
    }


def _bridge_close_response(ticket=12345678, price=1.08920, profit=42.0):
    return {"ticket": ticket, "close_price": price, "profit": profit, "comment": "ok"}


class TestCheckAndClosePositions:

    def _run(self, trades, spread_result, close_result, feedback_mock):
        """Helper to run check_and_close_positions() with mocked deps."""
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=None)
        mock_conn.cursor    = MagicMock(return_value=MagicMock(
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=None),
        ))

        with patch("core.execution_engine.trade_manager.sync_fetchall",
                   return_value=trades) as mock_fetch, \
             patch("core.execution_engine.trade_manager._get_spread_sync",
                   return_value=spread_result) as mock_spread, \
             patch("core.execution_engine.trade_manager._close_position_sync",
                   return_value=close_result) as mock_close, \
             patch("core.execution_engine.trade_manager.get_sync_db",
                   return_value=mock_conn), \
             patch("core.execution_engine.trade_manager._close_trade_in_db") as mock_db, \
             patch("core.execution_engine.trade_manager.asyncio.run") as mock_run, \
             patch.dict("sys.modules", {
                 "core.ai_engine.feedback_loop": MagicMock(
                     on_trade_closed=feedback_mock
                 )
             }):
            result = check_and_close_positions()

        return result, mock_spread, mock_close, mock_db, mock_run

    def test_tp_hit_buy_closes_trade(self):
        trade  = _make_open_trade()
        # bid = 1.08920 ≥ tp = 1.08900 → TP hit
        spread = _spread(bid=1.08920, ask=1.08921)
        close  = _bridge_close_response(price=1.08920, profit=42.0)

        n, _, mock_close, mock_db, _ = self._run(
            [trade], spread, close, AsyncMock()
        )
        assert n == 1
        mock_close.assert_called_once_with(12345678)
        mock_db.assert_called_once()

    def test_sl_hit_buy_closes_trade(self):
        trade  = _make_open_trade()
        # bid = 1.08190 ≤ sl = 1.08200 → SL hit
        spread = _spread(bid=1.08190, ask=1.08191)
        close  = _bridge_close_response(price=1.08190, profit=-30.0)

        n, _, mock_close, mock_db, _ = self._run(
            [trade], spread, close, AsyncMock()
        )
        assert n == 1

    def test_no_hit_does_not_close(self):
        trade  = _make_open_trade()
        # bid = 1.08600 — between sl=1.082 and tp=1.089 → no hit
        spread = _spread(bid=1.08600, ask=1.08601)

        n, _, mock_close, mock_db, _ = self._run(
            [trade], spread, None, AsyncMock()
        )
        assert n == 0
        mock_close.assert_not_called()
        mock_db.assert_not_called()

    def test_sell_tp_hit(self):
        trade  = _make_open_trade(
            direction="sell", entry_price=1.08900,
            stop_loss=1.09200, take_profit=1.08500,
        )
        # ask = 1.08490 ≤ tp = 1.08500 → TP hit
        spread = _spread(bid=1.08489, ask=1.08490)
        close  = _bridge_close_response(price=1.08490, profit=41.0)

        n, _, _, mock_db, _ = self._run([trade], spread, close, AsyncMock())
        assert n == 1

    def test_sell_sl_hit(self):
        trade  = _make_open_trade(
            direction="sell", entry_price=1.08900,
            stop_loss=1.09200, take_profit=1.08500,
        )
        # ask = 1.09210 ≥ sl = 1.09200 → SL hit
        spread = _spread(bid=1.09209, ask=1.09210)
        close  = _bridge_close_response(price=1.09210, profit=-31.0)

        n, _, _, mock_db, _ = self._run([trade], spread, close, AsyncMock())
        assert n == 1

    def test_feedback_loop_triggered_per_closed_trade(self):
        trade  = _make_open_trade()
        spread = _spread(bid=1.08920, ask=1.08921)
        close  = _bridge_close_response()
        fb     = AsyncMock()

        _, _, _, _, mock_run = self._run([trade], spread, close, fb)
        # asyncio.run() must be called once — it wraps on_trade_closed()
        mock_run.assert_called_once()

    def test_bridge_close_failure_still_updates_db(self):
        """If bridge close returns None (broker already closed), DB must still update."""
        trade  = _make_open_trade()
        spread = _spread(bid=1.08920, ask=1.08921)

        # _close_position_sync returns None — position already gone at broker
        n, _, _, mock_db, _ = self._run([trade], spread, None, AsyncMock())
        assert n == 1
        mock_db.assert_called_once()

    def test_spread_failure_skips_trade(self):
        trade = _make_open_trade()

        n, _, mock_close, mock_db, _ = self._run([trade], None, None, AsyncMock())
        assert n == 0
        mock_close.assert_not_called()

    def test_no_open_trades_returns_zero(self):
        n, _, mock_close, mock_db, _ = self._run([], None, None, AsyncMock())
        assert n == 0

    def test_multiple_trades_all_closed(self):
        t1 = _make_open_trade(id="t1", mt5_ticket=111)
        t2 = _make_open_trade(id="t2", mt5_ticket=222)
        spread = _spread(bid=1.08920, ask=1.08921)
        close  = _bridge_close_response()

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=None)
        mock_conn.cursor    = MagicMock(return_value=MagicMock(
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=None),
        ))

        with patch("core.execution_engine.trade_manager.sync_fetchall",
                   return_value=[t1, t2]), \
             patch("core.execution_engine.trade_manager._get_spread_sync",
                   return_value=spread), \
             patch("core.execution_engine.trade_manager._close_position_sync",
                   return_value=close), \
             patch("core.execution_engine.trade_manager.get_sync_db",
                   return_value=mock_conn), \
             patch("core.execution_engine.trade_manager._close_trade_in_db"), \
             patch("core.execution_engine.trade_manager.asyncio.run"), \
             patch.dict("sys.modules", {
                 "core.ai_engine.feedback_loop": MagicMock(on_trade_closed=AsyncMock())
             }):
            n = check_and_close_positions()

        assert n == 2
