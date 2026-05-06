"""telegram/community_drops.py — Community channel trade-result announcements."""
from __future__ import annotations
import os
from typing import Any

_RESULT_EMOJI  = {"win": "✅", "loss": "❌", "breakeven": "➖"}
_REGIME_EMOJI  = {"trending": "📈", "ranging": "↔️", "volatile": "⚡"}


def _format_result_drop(trade: dict[str, Any], signal: dict[str, Any]) -> str:
    result_r: float = trade.get("result_r") or trade.get("pnl_r") or 0.0
    if result_r > 0.05:
        outcome = "win"
    elif result_r < -0.05:
        outcome = "loss"
    else:
        outcome = "breakeven"

    emoji     = _RESULT_EMOJI[outcome]
    regime    = signal.get("regime", "unknown")
    r_emoji   = _REGIME_EMOJI.get(regime, "❓")
    ai_prob   = signal.get("ai_probability") or 0.0
    pair      = trade.get("pair", "?")
    direction = (trade.get("direction") or "").upper()

    return (
        f"{emoji} <b>Trade Closed</b>\n"
        f"Pair:      <code>{pair}</code>  {direction}\n"
        f"Result:    <b>{result_r:+.2f}R</b>\n"
        f"Regime:    {r_emoji} {regime.capitalize()}\n"
        f"AI conf:   {ai_prob:.0%}\n"
        f"Entry:     {signal.get('entry_price', 'n/a')}"
    )


async def post_result_drop(trade: dict[str, Any], signal: dict[str, Any]) -> None:
    channel_id = os.getenv("TELEGRAM_COMMUNITY_CHANNEL_ID", "")
    token      = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not channel_id or not token:
        return
    from telegram import Bot
    text = _format_result_drop(trade, signal)
    bot  = Bot(token=token)
    await bot.send_message(chat_id=channel_id, text=text, parse_mode="HTML")
