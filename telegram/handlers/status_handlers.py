"""
telegram/handlers/status_handlers.py — Starter+ status commands.

Commands:
  /status   — equity, open positions, bridge health, DD stage
  /pnl      — rolling 30-day P&L summary
  /trades   — last 10 closed trades
  /signals  — pending signals (with approve/reject hint for Trader+)
  /risk_state — current risk parameters
  /regime   — current market regime for all 5 tracked pairs
"""
from __future__ import annotations

from telegram.handlers import (
    _STARTER_PLANS, _TRADER_PLANS, _bot_db,
    _upgrade_text, _pnl_emoji, _DD_STAGE_NAME, _REGIME_EMOJI, PAIRS,
)


async def cmd_status(update, context) -> None:
    tg_id = str(update.effective_user.id)
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan, telegram_id FROM users WHERE telegram_id=$1", tg_id
        )
        if not user or user["plan"] not in _STARTER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/status", "starter"), parse_mode="HTML"
            )
            return

        account = await db.fetchrow(
            "SELECT equity, balance, open_positions, dd_stage "
            "FROM mt5_accounts WHERE user_id=$1::uuid",
            user["id"],
        )
        bridge = await db.fetchrow(
            "SELECT status FROM bridge_health ORDER BY checked_at DESC LIMIT 1"
        )

    if not account:
        await update.message.reply_text("No MT5 account linked. Use /link to connect.")
        return

    dd_label  = _DD_STAGE_NAME.get(account["dd_stage"] or 0, "Unknown")
    bridge_ok = (bridge and bridge["status"] == "ok") if bridge else False
    bridge_icon = "🟢" if bridge_ok else "🔴"

    text = (
        f"<b>Account Status</b>\n"
        f"Balance:    <code>{account['balance']:.2f}</code>\n"
        f"Equity:     <code>{account['equity']:.2f}</code>\n"
        f"Open trades: {account['open_positions'] or 0}\n"
        f"DD Stage:   {dd_label}\n"
        f"Bridge:     {bridge_icon}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_pnl(update, context) -> None:
    tg_id = str(update.effective_user.id)
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_id=$1", tg_id
        )
        if not user or user["plan"] not in _STARTER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/pnl", "starter"), parse_mode="HTML"
            )
            return

        row = await db.fetchrow(
            "SELECT total_trades, win_rate_pct, net_r, expectancy_r "
            "FROM mv_rolling_performance WHERE user_id=$1::uuid",
            user["id"],
        )

    if not row or not row["total_trades"]:
        await update.message.reply_text("No closed trades yet.")
        return

    emoji = _pnl_emoji(row["net_r"] or 0.0)
    text = (
        f"<b>30-Day Performance</b> {emoji}\n"
        f"Trades:      {row['total_trades']}\n"
        f"Win rate:    {row['win_rate_pct']:.1f}%\n"
        f"Net R:       {row['net_r']:.2f}R\n"
        f"Expectancy:  {row['expectancy_r']:.2f}R"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_trades(update, context) -> None:
    tg_id = str(update.effective_user.id)
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_id=$1", tg_id
        )
        if not user or user["plan"] not in _STARTER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/trades", "starter"), parse_mode="HTML"
            )
            return

        rows = await db.fetch(
            "SELECT pair, direction, result_r, closed_at "
            "FROM trades WHERE user_id=$1::uuid AND status='closed' "
            "ORDER BY closed_at DESC LIMIT 10",
            user["id"],
        )

    if not rows:
        await update.message.reply_text("No closed trades yet.")
        return

    lines = ["<b>Last 10 Trades</b>"]
    for r in rows:
        emoji = _pnl_emoji(r["result_r"] or 0.0)
        lines.append(
            f"{emoji} {r['pair']} {r['direction'].upper()}  "
            f"<code>{(r['result_r'] or 0.0):+.2f}R</code>"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_signals(update, context) -> None:
    tg_id = str(update.effective_user.id)
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_id=$1", tg_id
        )
        if not user or user["plan"] not in _STARTER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/signals", "starter"), parse_mode="HTML"
            )
            return

        rows = await db.fetch(
            "SELECT id, pair, direction, entry_price, ai_probability "
            "FROM trade_signals WHERE user_id=$1::uuid AND status='pending' "
            "ORDER BY triggered_at DESC LIMIT 10",
            user["id"],
        )

    if not rows:
        await update.message.reply_text("No pending signals.")
        return

    can_act = user["plan"] in _TRADER_PLANS
    lines   = ["<b>Pending Signals</b>"]
    for r in rows:
        sid = str(r["id"])[:8]
        lines.append(
            f"• {r['pair']} {r['direction'].upper()} @ {r['entry_price']}  "
            f"AI:{r['ai_probability']:.0%}  <code>{sid}</code>"
        )
    if can_act:
        lines.append("\n<i>Use /approve_&lt;id&gt; or /reject_&lt;id&gt;</i>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_risk_state(update, context) -> None:
    tg_id = str(update.effective_user.id)
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_id=$1", tg_id
        )
        if not user or user["plan"] not in _STARTER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/risk_state", "starter"), parse_mode="HTML"
            )
            return

        row = await db.fetchrow(
            "SELECT max_risk_pct, max_daily_dd_pct, max_total_dd_pct, "
            "       pause_on_dd_stage, current_daily_loss_r "
            "FROM risk_profiles WHERE user_id=$1::uuid",
            user["id"],
        )

    if not row:
        await update.message.reply_text("No risk profile found.")
        return

    text = (
        f"<b>Risk State</b>\n"
        f"Max risk/trade:  {row['max_risk_pct']:.1f}%\n"
        f"Daily DD limit:  {row['max_daily_dd_pct']:.1f}%\n"
        f"Total DD limit:  {row['max_total_dd_pct']:.1f}%\n"
        f"Pause at stage:  {row['pause_on_dd_stage']}\n"
        f"Today's loss:    {row['current_daily_loss_r']:.2f}R"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_regime(update, context) -> None:
    tg_id = str(update.effective_user.id)
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_id=$1", tg_id
        )
        if not user or user["plan"] not in _STARTER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/regime", "starter"), parse_mode="HTML"
            )
            return

        rows = await db.fetch(
            "SELECT pair, regime, adx "
            "FROM regime_cache WHERE pair = ANY($1::text[]) "
            "ORDER BY pair",
            list(PAIRS),
        )

    if not rows:
        await update.message.reply_text("Regime data not available yet.")
        return

    lines = ["<b>Market Regimes</b>"]
    regime_map = {r["pair"]: r for r in rows}
    for pair in PAIRS:
        r = regime_map.get(pair)
        if r:
            emoji = _REGIME_EMOJI.get(r["regime"], "❓")
            lines.append(f"{emoji} {pair}: {r['regime'].capitalize()}  ADX {r['adx']:.0f}")
        else:
            lines.append(f"❓ {pair}: n/a")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")
