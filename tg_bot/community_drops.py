"""telegram/community_drops.py — Community channel trade-result announcements.
Reads bot token and channel ID from the DB bot_config table (admin-configurable),
falling back to environment variables if the DB is unavailable.
"""
from __future__ import annotations
import os
from typing import Any

_RESULT_EMOJI = {"win": "✅", "loss": "❌", "breakeven": "➖"}
_REGIME_EMOJI = {"trending": "📈", "ranging": "↔️", "volatile": "⚡"}


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


async def _get_db_config() -> dict:
    """Read bot config from DB. Returns empty dict on any error."""
    try:
        from database.connection import _get_pool
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM bot_config WHERE id=1")
            return dict(row) if row else {}
    except Exception:
        return {}


async def post_result_drop(trade: dict[str, Any], signal: dict[str, Any]) -> None:
    cfg        = await _get_db_config()
    token      = cfg.get("telegram_bot_token")      or os.getenv("TELEGRAM_BOT_TOKEN", "")
    channel_id = cfg.get("telegram_community_channel") or os.getenv("TELEGRAM_COMMUNITY_CHANNEL_ID", "")

    if not cfg.get("results_drop_enabled", True):
        return
    if not channel_id or not token:
        return

    from telegram import Bot
    text = _format_result_drop(trade, signal)
    bot  = Bot(token=token)
    await bot.send_message(chat_id=channel_id, text=text, parse_mode="HTML")


async def post_signal_drop(signal: dict[str, Any]) -> None:
    """Broadcast a new signal to the signals channel."""
    cfg        = await _get_db_config()
    token      = cfg.get("telegram_bot_token")    or os.getenv("TELEGRAM_BOT_TOKEN", "")
    channel_id = cfg.get("telegram_signals_channel") or os.getenv("TELEGRAM_SIGNALS_CHANNEL_ID", "")

    if not cfg.get("signals_drop_enabled", True):
        return
    if not channel_id or not token:
        return

    pair      = signal.get("pair", "?")
    direction = (signal.get("direction") or "").upper()
    entry     = signal.get("entry_price", "market")
    sl        = signal.get("stop_loss", "—")
    tp        = signal.get("take_profit", "—")
    conf      = signal.get("ai_probability") or 0.0
    regime    = signal.get("regime", "unknown")

    text = (
        f"📊 <b>NEW SIGNAL</b>\n"
        f"Pair:      <code>{pair}</code>  {direction}\n"
        f"Entry:     <b>{entry}</b>\n"
        f"SL:        {sl}\n"
        f"TP:        {tp}\n"
        f"AI conf:   {conf:.0%}\n"
        f"Regime:    {_REGIME_EMOJI.get(regime, '❓')} {regime.capitalize()}"
    )

    from telegram import Bot
    bot = Bot(token=token)
    await bot.send_message(chat_id=channel_id, text=text, parse_mode="HTML")
