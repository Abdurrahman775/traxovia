"""
tg_bot/handlers/status_handlers.py — Starter+ status commands.

Commands:
  /status     — balance, open trades, bridge state, DD stage
  /pnl        — rolling 30-day P&L summary
  /trades     — last 10 closed trades
  /signals    — pending signals (with approve/reject hint for Trader+)
  /risk_state — current risk parameters
  /regime     — current market regime derived from ohlc_h4
"""
from __future__ import annotations

from tg_bot.handlers import (
    _STARTER_PLANS, _TRADER_PLANS, _bot_db,
    _upgrade_text, _pnl_emoji, _DD_STAGE_NAME, _REGIME_EMOJI, PAIRS,
)


async def cmd_status(update, context) -> None:
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan, telegram_chat_id FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _STARTER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/status", "starter"), parse_mode="HTML"
            )
            return

        account = await db.fetchrow(
            "SELECT account_balance, account_number, broker "
            "FROM mt5_accounts WHERE user_id=$1::uuid AND active=TRUE",
            user["id"],
        )
        risk = await db.fetchrow(
            "SELECT drawdown_stage, trading_allowed, daily_trades, daily_pnl_r, total_drawdown_pct "
            "FROM risk_state WHERE user_id=$1::uuid",
            user["id"],
        )
        bridge = await db.fetchrow(
            "SELECT trading_paused, last_heartbeat FROM bridge_state LIMIT 1"
        )
        open_count = await db.fetchval(
            "SELECT COUNT(*) FROM trades WHERE user_id=$1::uuid AND status='open'",
            user["id"],
        )

    if not account:
        await update.message.reply_text("No active MT5 account found. Add one in Settings.")
        return

    dd_stage   = (risk["drawdown_stage"] if risk else 0) or 0
    dd_label   = _DD_STAGE_NAME.get(dd_stage, f"Stage {dd_stage}")
    allowed    = (risk["trading_allowed"] if risk else True)
    paused     = (bridge["trading_paused"] if bridge else False)
    bridge_icon = "🔴" if paused else "🟢"
    trade_icon  = "✅" if allowed else "🚫"

    text = (
        f"<b>Account Status</b>\n"
        f"Account:      <code>{account['account_number']}</code>  ({account['broker'] or 'n/a'})\n"
        f"Balance:      <code>{float(account['account_balance'] or 0):.2f}</code>\n"
        f"Open trades:  {open_count or 0}\n"
        f"DD Stage:     {dd_label}\n"
        f"Trading:      {trade_icon} {'allowed' if allowed else 'halted'}\n"
        f"Bridge:       {bridge_icon} {'paused' if paused else 'active'}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_pnl(update, context) -> None:
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _STARTER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/pnl", "starter"), parse_mode="HTML"
            )
            return

        row = await db.fetchrow(
            """SELECT
                COUNT(*)                                    AS total_trades,
                SUM(pnl_r)                                  AS net_r,
                AVG(pnl_r)                                  AS expectancy_r,
                100.0 * SUM(CASE WHEN pnl_r > 0 THEN 1 ELSE 0 END)::float
                    / NULLIF(COUNT(*), 0)                   AS win_rate_pct
               FROM trades
               WHERE user_id=$1::uuid
                 AND status='closed'
                 AND entry_time >= NOW() - INTERVAL '30 days'""",
            user["id"],
        )

    if not row or not row["total_trades"]:
        await update.message.reply_text("No closed trades in the last 30 days.")
        return

    net_r      = float(row["net_r"] or 0.0)
    expectancy = float(row["expectancy_r"] or 0.0)
    win_rate   = float(row["win_rate_pct"] or 0.0)
    emoji      = _pnl_emoji(net_r)

    text = (
        f"<b>30-Day Performance</b> {emoji}\n"
        f"Trades:      {row['total_trades']}\n"
        f"Win rate:    {win_rate:.1f}%\n"
        f"Net R:       {net_r:+.2f}R\n"
        f"Expectancy:  {expectancy:+.2f}R"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_trades(update, context) -> None:
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _STARTER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/trades", "starter"), parse_mode="HTML"
            )
            return

        rows = await db.fetch(
            "SELECT pair, direction, pnl_r, exit_time "
            "FROM trades WHERE user_id=$1::uuid AND status='closed' "
            "ORDER BY exit_time DESC LIMIT 10",
            user["id"],
        )

    if not rows:
        await update.message.reply_text("No closed trades yet.")
        return

    lines = ["<b>Last 10 Trades</b>"]
    for r in rows:
        pnl   = float(r["pnl_r"] or 0.0)
        emoji = _pnl_emoji(pnl)
        lines.append(
            f"{emoji} {r['pair']} {(r['direction'] or '').upper()}  "
            f"<code>{pnl:+.2f}R</code>"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_signals(update, context) -> None:
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_chat_id=$1", tg_id
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
        prob = float(r["ai_probability"] or 0)
        lines.append(
            f"• {r['pair']} {(r['direction'] or '').upper()} @ {r['entry_price']}  "
            f"AI:{prob:.0%}  <code>{sid}</code>"
        )
    if can_act:
        lines.append("\n<i>Use /approve_&lt;id&gt; or /reject_&lt;id&gt;</i>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_risk_state(update, context) -> None:
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan, base_risk_pct, risk_max_pct, risk_max_drawdown_pct, "
            "       risk_daily_pct, max_trades_per_day "
            "FROM users WHERE telegram_chat_id=$1",
            tg_id,
        )
        if not user or user["plan"] not in _STARTER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/risk_state", "starter"), parse_mode="HTML"
            )
            return

        rs = await db.fetchrow(
            "SELECT drawdown_stage, trading_allowed, daily_trades, daily_pnl_r, total_drawdown_pct "
            "FROM risk_state WHERE user_id=$1::uuid",
            user["id"],
        )

    dd_stage = (rs["drawdown_stage"] if rs else 0) or 0
    dd_label = _DD_STAGE_NAME.get(dd_stage, f"Stage {dd_stage}")
    allowed  = (rs["trading_allowed"] if rs else True)

    text = (
        f"<b>Risk State</b>\n"
        f"Base risk/trade: {float(user['base_risk_pct'] or 0):.2f}%\n"
        f"Max risk/trade:  {float(user['risk_max_pct'] or 0):.2f}%\n"
        f"Total DD limit:  {float(user['risk_max_drawdown_pct'] or 0):.1f}%\n"
        f"Daily DD limit:  {float(user['risk_daily_pct'] or 0):.1f}%\n"
        f"Max trades/day:  {user['max_trades_per_day'] or 'n/a'}\n"
        f"Today's trades:  {(rs['daily_trades'] if rs else 0) or 0}\n"
        f"Today's P&L:     {float((rs['daily_pnl_r'] if rs else 0) or 0):+.2f}R\n"
        f"DD Stage:        {dd_label}\n"
        f"Trading:         {'✅ allowed' if allowed else '🚫 halted'}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_accounts(update, context) -> None:
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _STARTER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/accounts", "starter"), parse_mode="HTML"
            )
            return

        rows = await db.fetch(
            "SELECT account_number, broker, account_balance, is_demo, active "
            "FROM mt5_accounts WHERE user_id=$1::uuid ORDER BY active DESC, created_at",
            user["id"],
        )

    if not rows:
        await update.message.reply_text("No MT5 accounts linked. Add one in Settings → MT5.")
        return

    lines = ["<b>MT5 Accounts</b>"]
    for r in rows:
        status  = "🟢" if r["active"] else "⚫"
        kind    = "Demo" if r["is_demo"] else "Live"
        balance = float(r["account_balance"] or 0)
        lines.append(
            f"{status} <code>{r['account_number']}</code>  {r['broker']}  "
            f"[{kind}]  <b>${balance:,.2f}</b>"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_regime(update, context) -> None:
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _STARTER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/regime", "starter"), parse_mode="HTML"
            )
            return

        # Derive simple regime from latest H4 candles: trending if ADX-proxy > threshold
        rows = await db.fetch(
            """SELECT pair,
                      AVG(high - low)          AS avg_range,
                      STDDEV(close - open)     AS vol,
                      COUNT(*)                 AS candles
               FROM ohlc_h4
               WHERE pair = ANY($1::text[])
                 AND time >= NOW() - INTERVAL '7 days'
               GROUP BY pair""",
            list(PAIRS),
        )

    if not rows:
        await update.message.reply_text("Regime data not available yet.")
        return

    lines = ["<b>Market Regimes (H4)</b>"]
    regime_map = {r["pair"]: r for r in rows}
    for pair in PAIRS:
        r = regime_map.get(pair)
        if r and r["candles"] and r["avg_range"]:
            vol_ratio = float(r["vol"] or 0) / float(r["avg_range"])
            if vol_ratio > 0.3:
                regime = "trending"
            elif vol_ratio > 0.1:
                regime = "ranging"
            else:
                regime = "quiet"
            emoji = _REGIME_EMOJI.get(regime, "❓")
            lines.append(f"{emoji} {pair}: {regime.capitalize()}")
        else:
            lines.append(f"❓ {pair}: n/a")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")
