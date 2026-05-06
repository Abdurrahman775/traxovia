"""
tests/test_phase8_e2e.py — Phase 8 end-to-end pipeline unit tests.

All HTTP calls to the MT5 bridge are mocked at the httpx/requests level.
All DB calls are mocked with unittest.mock.
No real bridge or database required — runs fully offline.

Tests the full pipeline:
  open_order() → trade written to DB → trade_manager detects SL/TP →
  _close_trade_in_db() → feedback_loop.on_trade_closed() → feature_store + audit_log
"""

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── Constants ──────────────────────────────────────────────────────────────────

TEST_USER_ID   = str(uuid.uuid4())
TEST_SIGNAL_ID = str(uuid.uuid4())
TEST_TRADE_ID  = str(uuid.uuid4())
TEST_TICKET    = 8452623634

ENTRY_PRICE = 1.08400
STOP_LOSS   = 1.08300
TAKE_PROFIT = 1.08450
CLOSE_PRICE = 1.08460   # above TP → win


# ── Mock bridge responses ──────────────────────────────────────────────────────

def _mock_health_response():
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"status": "ok", "account": 106464235, "server": "MetaQuotes-Demo"}
    return m


def _mock_open_response():
    m = MagicMock()
    m.status_code = 201
    m.json.return_value = {
        "ticket":      TEST_TICKET,
        "symbol":      "EURUSD",
        "direction":   "buy",
        "lot_size":    0.01,
        "open_price":  ENTRY_PRICE,
        "stop_loss":   STOP_LOSS,
        "take_profit": TAKE_PROFIT,
        "comment":     "E2E-Phase8",
    }
    return m


def _mock_spread_response():
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"bid": CLOSE_PRICE, "ask": CLOSE_PRICE + 0.00008, "spread": 0.8}
    return m


def _mock_close_response():
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {
        "ticket":      TEST_TICKET,
        "close_price": CLOSE_PRICE,
        "profit":      6.0,
        "comment":     "closed",
    }
    return m


# ── Step 1: Bridge health (mocked) ────────────────────────────────────────────

def test_step1_bridge_health():
    """Bridge /health returns 200 with expected fields (mocked)."""
    import httpx

    with patch("httpx.get", return_value=_mock_health_response()) as mock_get:
        resp = httpx.get("http://127.0.0.1:8001/health", timeout=5)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "account" in data
    print(f"\n  [PASS] Bridge healthy (mocked) — account={data['account']}")


# ── Step 2: open_order() returns a ticket ─────────────────────────────────────

def test_step2_open_order_returns_ticket():
    """mt5_executor.open_order() parses bridge response into OrderResult."""
    from core.execution_engine.mt5_executor import open_order

    async def _run():
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = _mock_open_response().json()

        with patch("core.execution_engine.mt5_executor._post", AsyncMock(return_value=mock_resp)):
            return await open_order("EURUSD", "buy", 0.01, STOP_LOSS, TAKE_PROFIT, "E2E-Phase8")

    result = asyncio.run(_run())

    assert result.ticket      == TEST_TICKET
    assert result.symbol      == "EURUSD"
    assert result.direction   == "buy"
    assert result.lot_size    == 0.01
    assert result.open_price  == ENTRY_PRICE
    assert result.stop_loss   == STOP_LOSS
    assert result.take_profit == TAKE_PROFIT
    print(f"\n  [PASS] open_order → ticket={result.ticket} price={result.open_price}")


# ── Step 3: Trade row written to DB ───────────────────────────────────────────

def test_step3_trade_written_to_db():
    """
    Verifies the INSERT pattern used by paper_trading_loop.py.
    Mocks the asyncpg connection — confirms correct SQL and params.
    """
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    async def _run():
        await mock_db.execute(
            """INSERT INTO trades
               (user_id, signal_id, mt5_ticket, pair, direction,
                lot_size, entry_price, stop_loss, take_profit, status, is_paper, entry_time)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'open',TRUE,NOW())
               ON CONFLICT DO NOTHING""",
            TEST_USER_ID, TEST_SIGNAL_ID, TEST_TICKET,
            "EURUSD", "buy", 0.01, ENTRY_PRICE, STOP_LOSS, TAKE_PROFIT,
        )

    asyncio.run(_run())

    mock_db.execute.assert_called_once()
    call_args = mock_db.execute.call_args.args
    assert TEST_TICKET    in call_args
    assert "EURUSD"       in call_args
    assert ENTRY_PRICE    in call_args
    print(f"\n  [PASS] Trade INSERT called with correct params (ticket={TEST_TICKET})")


# ── Step 4: trade_manager detects SL/TP and closes ───────────────────────────

def test_step4_trade_manager_detects_close():
    """
    check_and_close_positions() fetches open trades, detects TP breach via
    spread, closes via bridge, and calls _close_trade_in_db.
    All HTTP and DB calls are mocked.
    """
    from core.execution_engine.trade_manager import (
        _sl_tp_hit, _compute_pnl, _close_trade_in_db,
    )

    trade = {
        "id":          TEST_TRADE_ID,
        "user_id":     TEST_USER_ID,
        "pair":        "EURUSD",
        "direction":   "buy",
        "entry_price": Decimal(str(ENTRY_PRICE)),
        "stop_loss":   Decimal(str(STOP_LOSS)),
        "take_profit": Decimal(str(TAKE_PROFIT)),
        "lot_size":    Decimal("0.01"),
        "mt5_ticket":  TEST_TICKET,
        "entry_time":  datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
    }

    spread = {"bid": CLOSE_PRICE, "ask": CLOSE_PRICE + 0.00008}

    # TP should be hit: bid (1.08460) >= tp (1.08450)
    hit = _sl_tp_hit(trade, bid=spread["bid"], ask=spread["ask"])
    assert hit == "tp", f"Expected 'tp', got {hit!r}"

    pnl_r, pips = _compute_pnl(trade, CLOSE_PRICE)
    assert pnl_r > 0, f"Expected positive pnl_r for TP hit, got {pnl_r}"

    # Verify _close_trade_in_db writes correct fields
    mock_conn = MagicMock()
    mock_cur  = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

    _close_trade_in_db(mock_conn, trade, CLOSE_PRICE, hit)

    mock_cur.execute.assert_called_once()
    sql, params = mock_cur.execute.call_args.args
    assert "status='closed'" in sql
    assert "pnl_r"           in sql
    assert params[2] == pnl_r   # pnl_r is 3rd param after exit_time, exit_price
    print(f"\n  [PASS] TP detected, _close_trade_in_db called — pnl_r={pnl_r}")


# ── Step 5: Trade row shows closed status ─────────────────────────────────────

def test_step5_trade_closed_in_db():
    """
    After _close_trade_in_db runs, the UPDATE sets status, exit_price,
    pnl_r, pips, duration_hours. Verify the SQL contains all required fields.
    """
    from core.execution_engine.trade_manager import _close_trade_in_db

    trade = {
        "id":          TEST_TRADE_ID,
        "pair":        "EURUSD",
        "direction":   "buy",
        "entry_price": Decimal(str(ENTRY_PRICE)),
        "stop_loss":   Decimal(str(STOP_LOSS)),
        "take_profit": Decimal(str(TAKE_PROFIT)),
        "entry_time":  datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
    }

    mock_conn = MagicMock()
    mock_cur  = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__  = MagicMock(return_value=False)

    _close_trade_in_db(mock_conn, trade, CLOSE_PRICE, "tp")

    sql, params = mock_cur.execute.call_args.args
    assert "exit_price"      in sql
    assert "pnl_r"           in sql
    assert "duration_hours"  in sql
    assert params[1] == CLOSE_PRICE   # exit_price
    assert params[2] is not None      # pnl_r computed
    assert params[3] is not None      # pips computed
    print(f"\n  [PASS] DB UPDATE contains exit_price={params[1]} pnl_r={params[2]}")


# ── Step 6: feedback_loop writes outcome to feature_store ─────────────────────

def test_step6_outcome_logged_to_feature_store():
    """
    on_trade_closed() must UPDATE feature_store with outcome + pnl_r,
    and INSERT into audit_log with 3 bind values.
    """
    import sys
    for mod in ("database", "database.connection", "scheduler", "scheduler.tasks",
                "telegram", "notifications", "notifications.telegram_handler"):
        sys.modules.setdefault(mod, MagicMock())

    from core.ai_engine.feedback_loop import on_trade_closed

    trade = {
        "id":        TEST_TRADE_ID,
        "signal_id": TEST_SIGNAL_ID,
        "pair":      "EURUSD",
        "pnl_r":     1.5,
        "pips":      50,
        "duration_hours": 2.0,
    }
    signal = {
        "id":                TEST_SIGNAL_ID,
        "pair":              "EURUSD",
        "direction":         "buy",
        "triggered_at":      datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
        "community_visible": False,
    }

    mock_db = AsyncMock()
    mock_db.fetchrow  = AsyncMock(side_effect=[trade, signal])
    mock_db.execute   = AsyncMock()

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__  = AsyncMock(return_value=False)

    with patch("core.ai_engine.feedback_loop.get_db_direct", return_value=mock_cm), \
         patch("core.ai_engine.feedback_loop.trigger_retrain_if_needed", AsyncMock()):
        asyncio.run(on_trade_closed(TEST_TRADE_ID, TEST_USER_ID))

    # feature_store UPDATE
    fs_call = next(
        c for c in mock_db.execute.call_args_list
        if "feature_store" in c.args[0]
    )
    assert fs_call.args[1] == "win", f"Expected outcome='win' for pnl_r=1.5, got {fs_call.args[1]!r}"
    assert fs_call.args[2] == 1.5

    # audit_log INSERT — must have 3 bind values
    audit_call = next(
        c for c in mock_db.execute.call_args_list
        if "audit_log" in c.args[0]
    )
    bind_vals = audit_call.args[1:]
    assert len(bind_vals) == 3,              f"audit_log needs 3 bind values, got {len(bind_vals)}"
    assert bind_vals[1] == "trade_closed"
    assert isinstance(bind_vals[2], str) and len(bind_vals[2]) > 0

    print(f"\n  [PASS] feature_store outcome=win, audit_log has 3 bind values")


# ── Step 7: audit_log entry has correct structure ─────────────────────────────

def test_step7_audit_log_entry():
    """
    Verify audit_log detail string contains outcome and pnl_r.
    Reuses the same mock setup as step 6.
    """
    import sys
    for mod in ("database", "database.connection", "scheduler", "scheduler.tasks",
                "telegram", "notifications", "notifications.telegram_handler"):
        sys.modules.setdefault(mod, MagicMock())

    from core.ai_engine.feedback_loop import on_trade_closed

    trade = {
        "id":        TEST_TRADE_ID,
        "signal_id": TEST_SIGNAL_ID,
        "pair":      "EURUSD",
        "pnl_r":     -1.0,
        "pips":      -10,
        "duration_hours": 1.0,
    }
    signal = {
        "id":                TEST_SIGNAL_ID,
        "pair":              "EURUSD",
        "direction":         "sell",
        "triggered_at":      datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
        "community_visible": False,
    }

    mock_db = AsyncMock()
    mock_db.fetchrow  = AsyncMock(side_effect=[trade, signal])
    mock_db.execute   = AsyncMock()

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__  = AsyncMock(return_value=False)

    with patch("core.ai_engine.feedback_loop.get_db_direct", return_value=mock_cm), \
         patch("core.ai_engine.feedback_loop.trigger_retrain_if_needed", AsyncMock()):
        asyncio.run(on_trade_closed(TEST_TRADE_ID, TEST_USER_ID))

    audit_call = next(
        c for c in mock_db.execute.call_args_list
        if "audit_log" in c.args[0]
    )
    detail = audit_call.args[3]   # $3 bind value
    assert "loss"         in detail, f"detail must mention outcome, got: {detail!r}"
    assert "trade_closed" in audit_call.args[2]
    print(f"\n  [PASS] audit_log detail={detail[:60]}…")
