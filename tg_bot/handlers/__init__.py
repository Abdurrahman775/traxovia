"""telegram/handlers/__init__.py — Shared constants and helpers for all handlers."""
from __future__ import annotations
import os
from contextlib import asynccontextmanager
import asyncpg

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD"]

_STARTER_PLANS = {"starter", "trader", "pro", "elite", "trial"}
_TRADER_PLANS  = {"trader", "pro", "elite"}
_PRO_PLANS     = {"pro", "elite"}

_DD_STAGE_NAME = {0: "Normal", 1: "Caution (10%)", 2: "Restricted (12%)", 3: "PAUSED (15%)"}
_REGIME_EMOJI  = {"trending": "📈", "ranging": "↔️", "volatile": "⚡"}

PLAN_LABELS = {
    "community": "Community (Free)",
    "starter":   "Starter — $29/mo",
    "trader":    "Trader — $79/mo",
    "pro":       "Pro — $149/mo",
    "elite":     "Elite — $299/mo",
    "trial":     "Trial",
}

TIER_COMMANDS = """
<b>Your available commands by plan:</b>

🆓 <b>All users</b>
/start · /help · /link · /unlink · /me

📊 <b>Starter+</b>
/status · /pnl · /trades · /signals · /accounts · /risk_state · /regime

🔁 <b>Trader+</b>
/approve · /reject · /pause · /resume · /bridge_status

⚙️ <b>Pro+</b>
/risk · /mode · /pairs · /setsl · /weekly · /dd_override

🔑 <b>Elite</b>
/api_key
"""


def _pnl_emoji(r: float) -> str:
    if r > 0.05:  return "✅"
    if r < -0.05: return "❌"
    return "➖"


def _upgrade_text(command: str, required_plan: str) -> str:
    return (
        f"⬆️ <b>{command}</b> requires the <b>{required_plan.upper()}</b> plan.\n"
        f"Upgrade in your Traxovia AI dashboard."
    )


@asynccontextmanager
async def _bot_db():
    """Async context manager yielding an asyncpg connection."""
    db_url = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_url)
    try:
        yield conn
    finally:
        await conn.close()
