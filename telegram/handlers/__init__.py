"""telegram/handlers/__init__.py — Shared constants and helpers for all handlers."""
from __future__ import annotations
from database.sync_connection import get_sync_db

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30"]

_STARTER_PLANS = {"starter", "trader", "pro", "elite", "trial"}
_TRADER_PLANS  = {"trader", "pro", "elite"}
_PRO_PLANS     = {"pro", "elite"}

_DD_STAGE_NAME = {0: "Normal", 1: "Stage 1 (0.5%)", 2: "Stage 2 (0.25%)", 3: "PAUSED"}
_REGIME_EMOJI  = {"trending": "📈", "ranging": "↔️", "volatile": "⚡"}


def _pnl_emoji(r: float) -> str:
    if r > 0.05:  return "✅"
    if r < -0.05: return "❌"
    return "➖"


def _upgrade_text(command: str, required_plan: str) -> str:
    return f"⬆️ <b>{command}</b> requires {required_plan.upper()} plan. Upgrade at tradingai.com"


def _bot_db():
    """Return a synchronous psycopg2 connection for use in Telegram handlers."""
    return get_sync_db()
