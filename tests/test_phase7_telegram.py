"""
tests/test_phase7_telegram.py — Unit tests for Phase 7 Telegram handlers.

Four tests:
  1. /status blocked for community-plan user
  2. /approve blocked for starter-plan user
  3. Community result drop formats message correctly
  4. /regime returns correct data for all 5 pairs

All tests mock _bot_db and the PTB Bot class so no real DB or Telegram API
calls are made.  The project's telegram/ package shadows python-telegram-bot,
so all PTB class usage is faked via MagicMock.
"""
from __future__ import annotations

import sys
import types
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── PTB stub setup ────────────────────────────────────────────────────────────
# The project's telegram/ package is already on sys.path.  We inject a fake
# 'Bot' attribute onto it so lazy `from telegram import Bot` inside handlers
# resolves to a MagicMock rather than the real PTB class (which isn't installed).

import telegram as _tg_pkg      # project's telegram/__init__.py
_tg_pkg.Bot = MagicMock()       # type: ignore[attr-defined]


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_update(text: str = "/status") -> MagicMock:
    """Minimal PTB Update stub."""
    update  = MagicMock()
    update.effective_user.id = 111222333
    update.message.text      = text
    update.message.reply_text = AsyncMock()
    return update


def _make_context(args: list[str] | None = None) -> MagicMock:
    ctx      = MagicMock()
    ctx.args = args or []
    return ctx


@asynccontextmanager
async def _mock_bot_db(mock_db):
    """Drop-in replacement for telegram.handlers._bot_db."""
    yield mock_db


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — /status blocked for community plan
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_status_blocked_for_community():
    """
    cmd_status must reply with an upgrade message when the user's plan is
    'community' (not in _STARTER_PLANS).
    """
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value={"id": "uid-001", "plan": "community"})

    update  = _make_update("/status")
    context = _make_context()

    with patch("telegram.handlers.status_handlers._bot_db", lambda: _mock_bot_db(db)):
        from telegram.handlers.status_handlers import cmd_status
        await cmd_status(update, context)

    reply_text = update.message.reply_text.call_args[0][0]
    assert "upgrade" in reply_text.lower() or "starter" in reply_text.lower(), (
        f"Expected upgrade prompt for community plan, got: {reply_text!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — /approve blocked for starter plan
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_approve_blocked_for_starter():
    """
    cmd_approve must reply with an upgrade message when the user's plan is
    'starter' (not in _TRADER_PLANS).
    """
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value={"id": "uid-002", "plan": "starter"})

    update          = _make_update("/approve_abcd1234")
    update.message.text = "/approve_abcd1234"
    context         = _make_context()

    with patch("telegram.handlers.trade_handlers._bot_db", lambda: _mock_bot_db(db)):
        from telegram.handlers.trade_handlers import cmd_approve
        await cmd_approve(update, context)

    reply_text = update.message.reply_text.call_args[0][0]
    assert "upgrade" in reply_text.lower() or "trader" in reply_text.lower(), (
        f"Expected upgrade prompt for starter plan, got: {reply_text!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Community result drop formats message correctly
# ═══════════════════════════════════════════════════════════════════════════════

def test_community_drop_format():
    """
    _format_result_drop must include the pair, numeric result, and regime.
    This is a pure function — no I/O.
    """
    from telegram.community_drops import _format_result_drop

    trade = {
        "pair":      "EURUSD",
        "direction": "buy",
        "result_r":  1.5,
    }
    signal = {
        "regime":         "trending",
        "ai_probability": 0.82,
        "entry_price":    1.0850,
    }

    msg = _format_result_drop(trade, signal)

    assert "EURUSD" in msg,    f"Pair missing from drop: {msg!r}"
    assert "1.50" in msg or "+1.50" in msg, f"Result R missing: {msg!r}"
    assert "trending" in msg.lower() or "Trending" in msg, f"Regime missing: {msg!r}"
    assert "✅" in msg,         f"Win emoji missing from winning trade: {msg!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — /regime returns correct regime for all 5 pairs
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_regime_returns_all_5_pairs():
    """
    cmd_regime must include all 5 tracked pairs in its reply when the DB
    returns one regime row per pair.
    """
    from telegram.handlers import PAIRS

    regime_rows = [
        {"pair": pair, "regime": "trending", "adx": 28.5}
        for pair in PAIRS
    ]

    db = AsyncMock()
    # fetchrow for user lookup returns trader plan
    db.fetchrow = AsyncMock(return_value={"id": "uid-003", "plan": "trader"})
    db.fetch    = AsyncMock(return_value=regime_rows)

    update  = _make_update("/regime")
    context = _make_context()

    with patch("telegram.handlers.status_handlers._bot_db", lambda: _mock_bot_db(db)):
        from telegram.handlers.status_handlers import cmd_regime
        await cmd_regime(update, context)

    reply_text = update.message.reply_text.call_args[0][0]
    for pair in PAIRS:
        assert pair in reply_text, (
            f"Pair {pair} missing from /regime reply: {reply_text!r}"
        )
