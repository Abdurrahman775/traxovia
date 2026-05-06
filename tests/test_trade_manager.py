"""
tests/test_trade_manager.py — Unit tests for trade_manager.py async path.
Run: pytest tests/test_trade_manager.py -v
"""

import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Pre-mock feedback_loop to avoid telegram/notifications import at collection time
_TM_MOCKED2 = ("core.ai_engine", "core.ai_engine.feedback_loop")
_tm2_pre = {m for m in _TM_MOCKED2 if m in sys.modules}
for _mod in _TM_MOCKED2:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from core.execution_engine.trade_manager import check_open_trades, _sl_tp_hit, _compute_pnl

for _m in _TM_MOCKED2:
    if _m not in _tm2_pre:
        sys.modules.pop(_m, None)


def _mock_trade(**overrides):
    base = {
        "id": "t-1", "user_id": "u-1", "pair": "EURUSD",
        "direction": "buy", "entry_price": 1.0850, "stop_loss": 1.0820,
        "take_profit": 1.0890, "lot_size": 0.01, "mt5_ticket": 111,
        "entry_time": None,
    }
    base.update(overrides)
    return base


def _mock_db_direct(trades):
    db = AsyncMock()
    db.fetch   = AsyncMock(return_value=trades)
    db.execute = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=db)
    mock_cm.__aexit__  = AsyncMock(return_value=False)
    return mock_cm, db


# ── _sl_tp_hit ─────────────────────────────────────────────────────────────────

def test_sl_tp_hit_buy_tp():
    trade = _mock_trade()
    assert _sl_tp_hit(trade, bid=1.0890, ask=1.0891) == "tp"

def test_sl_tp_hit_buy_sl():
    trade = _mock_trade()
    assert _sl_tp_hit(trade, bid=1.0820, ask=1.0821) == "sl"

def test_sl_tp_hit_buy_none():
    trade = _mock_trade()
    assert _sl_tp_hit(trade, bid=1.0855, ask=1.0856) is None


# ── _compute_pnl ───────────────────────────────────────────────────────────────

def test_compute_pnl_buy_win():
    trade = _mock_trade()
    pnl_r, pips = _compute_pnl(trade, 1.0880)
    assert pnl_r == pytest.approx(1.0, abs=0.001)
    assert pips  == pytest.approx(30.0, abs=0.2)

def test_compute_pnl_zero_risk():
    trade = _mock_trade(entry_price=1.085, stop_loss=1.085)
    pnl_r, _ = _compute_pnl(trade, 1.090)
    assert pnl_r == 0.0


# ── check_open_trades ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_open_trades_returns_zero():
    mock_cm, _ = _mock_db_direct([])
    with patch("core.execution_engine.trade_manager.get_db_direct", return_value=mock_cm):
        result = await check_open_trades()
    assert result == {"checked": 0, "closed": 0}


@pytest.mark.asyncio
async def test_no_hit_does_not_close():
    trade = _mock_trade()
    mock_cm, db = _mock_db_direct([trade])
    spread = {"bid": 1.0855, "ask": 1.0856}

    with patch("core.execution_engine.trade_manager.get_db_direct", return_value=mock_cm), \
         patch("core.execution_engine.trade_manager._get_spread_async", AsyncMock(return_value=spread)):
        result = await check_open_trades()

    assert result["closed"] == 0
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_tp_hit_closes_trade_and_triggers_feedback():
    trade = _mock_trade()
    mock_cm, db = _mock_db_direct([trade])
    spread     = {"bid": 1.0890, "ask": 1.0891}
    close_data = {"close_price": 1.0890, "profit": 40.0, "ticket": 111, "comment": "ok"}

    with patch("core.execution_engine.trade_manager.get_db_direct", return_value=mock_cm), \
         patch("core.execution_engine.trade_manager._get_spread_async", AsyncMock(return_value=spread)), \
         patch("core.execution_engine.trade_manager._close_position_async", AsyncMock(return_value=close_data)), \
         patch("core.ai_engine.feedback_loop.on_trade_closed", AsyncMock()) as mock_fb:
        result = await check_open_trades()

    assert result["closed"] == 1
    mock_fb.assert_called_once_with("t-1", "u-1")
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_spread_failure_skips_trade():
    trade = _mock_trade()
    mock_cm, db = _mock_db_direct([trade])

    with patch("core.execution_engine.trade_manager.get_db_direct", return_value=mock_cm), \
         patch("core.execution_engine.trade_manager._get_spread_async", AsyncMock(return_value=None)):
        result = await check_open_trades()

    assert result["closed"] == 0
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_error_on_one_trade_does_not_stop_others():
    t1 = _mock_trade(id="t-1", mt5_ticket=1)
    t2 = _mock_trade(id="t-2", mt5_ticket=2)
    mock_cm, db = _mock_db_direct([t1, t2])

    call_count = 0
    async def _spread(client, symbol):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("bridge error")
        return {"bid": 1.0890, "ask": 1.0891}

    close_data = {"close_price": 1.0890, "profit": 40.0, "ticket": 2, "comment": "ok"}

    with patch("core.execution_engine.trade_manager.get_db_direct", return_value=mock_cm), \
         patch("core.execution_engine.trade_manager._get_spread_async", side_effect=_spread), \
         patch("core.execution_engine.trade_manager._close_position_async", AsyncMock(return_value=close_data)), \
         patch("core.ai_engine.feedback_loop.on_trade_closed", AsyncMock()):
        result = await check_open_trades()

    assert result["checked"] == 2
    assert result["closed"]  == 1
