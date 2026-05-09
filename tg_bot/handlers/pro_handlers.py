"""
tg_bot/handlers/pro_handlers.py — Pro+ advanced commands.

Commands:
  /risk           — show/update risk parameters
  /mode           — switch trading mode (auto/manual/paper)
  /weekly         — weekly confluence bias summary
  /dd_override    — override drawdown stage (emergency use)
  /bridge_status  — detailed bridge diagnostics
  /pairs          — view or toggle active trading pairs (Pro+)
  /setsl          — override stop-loss pips for next signal (Pro+)
  /api_key        — generate or rotate API key (Elite+)
"""
from __future__ import annotations
import json
import secrets

from tg_bot.handlers import _PRO_PLANS, _TRADER_PLANS, _bot_db, _upgrade_text, _DD_STAGE_NAME, PAIRS

_ELITE_PLANS = {"elite"}


async def cmd_risk(update, context) -> None:
    """
    /risk                    — show current risk params
    /risk base_risk_pct=1.5  — update a single param
    """
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan, base_risk_pct, risk_max_pct, "
            "       risk_max_drawdown_pct, risk_daily_pct, max_trades_per_day "
            "FROM users WHERE telegram_chat_id=$1",
            tg_id,
        )
        if not user or user["plan"] not in _PRO_PLANS:
            await update.message.reply_text(
                _upgrade_text("/risk", "pro"), parse_mode="HTML"
            )
            return

        args = context.args or []
        if args:
            allowed = {
                "base_risk_pct", "risk_max_pct",
                "risk_max_drawdown_pct", "risk_daily_pct", "max_trades_per_day",
            }
            updates = {}
            for arg in args:
                if "=" not in arg:
                    continue
                k, _, v = arg.partition("=")
                if k not in allowed:
                    await update.message.reply_text(
                        f"Unknown param <code>{k}</code>. Allowed: {', '.join(sorted(allowed))}",
                        parse_mode="HTML",
                    )
                    return
                try:
                    updates[k] = int(v) if k == "max_trades_per_day" else float(v)
                except ValueError:
                    await update.message.reply_text(f"Invalid value for {k}: {v!r}")
                    return

            if not updates:
                await update.message.reply_text(
                    "Usage: /risk base_risk_pct=1.0 risk_max_pct=2.0"
                )
                return

            set_clause = ", ".join(f"{col}=${i+1}" for i, col in enumerate(updates))
            vals       = list(updates.values())
            vals.append(user["id"])
            await db.execute(
                f"UPDATE users SET {set_clause}, updated_at=NOW() WHERE id=${len(vals)}::uuid",
                *vals,
            )
            await db.execute(
                "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
                user["id"], "risk_change", f"updated risk params via telegram: {updates}",
            )
            await update.message.reply_text(
                f"✅ Risk params updated: {updates}", parse_mode="HTML"
            )
            return

    text = (
        f"<b>Risk Parameters</b>\n"
        f"Base risk/trade: {float(user['base_risk_pct'] or 0):.2f}%\n"
        f"Max risk/trade:  {float(user['risk_max_pct'] or 0):.2f}%\n"
        f"Total DD limit:  {float(user['risk_max_drawdown_pct'] or 0):.1f}%\n"
        f"Daily DD limit:  {float(user['risk_daily_pct'] or 0):.1f}%\n"
        f"Max trades/day:  {user['max_trades_per_day'] or 'n/a'}\n\n"
        "<i>To update: /risk base_risk_pct=1.5</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_mode(update, context) -> None:
    """
    /mode auto            — enable full automation
    /mode signal_approval — switch to manual approval
    /mode paper           — paper trading
    """
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _PRO_PLANS:
            await update.message.reply_text(
                _upgrade_text("/mode", "pro"), parse_mode="HTML"
            )
            return

        valid_modes = ("auto_trade", "signal_approval", "paper")
        args = context.args or []
        if not args or args[0] not in valid_modes:
            await update.message.reply_text(
                f"Usage: /mode &lt;{'|'.join(valid_modes)}&gt;", parse_mode="HTML"
            )
            return

        mode = args[0]
        await db.execute(
            "UPDATE users SET trading_mode=$1, updated_at=NOW() WHERE id=$2::uuid",
            mode, user["id"],
        )
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
            user["id"], "risk_change", f"trading mode changed to {mode} via telegram",
        )

    icon = "🤖" if mode == "auto_trade" else ("📋" if mode == "signal_approval" else "📄")
    await update.message.reply_text(
        f"{icon} Trading mode set to <b>{mode}</b>.", parse_mode="HTML"
    )


async def cmd_weekly(update, context) -> None:
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _PRO_PLANS:
            await update.message.reply_text(
                _upgrade_text("/weekly", "pro"), parse_mode="HTML"
            )
            return

        rows = await db.fetch(
            """SELECT pair,
                      FIRST_VALUE(close) OVER (PARTITION BY pair ORDER BY time DESC) AS last_close,
                      AVG(close) OVER (PARTITION BY pair)                             AS avg_close
               FROM ohlc_w1
               WHERE pair = ANY($1::text[])
                 AND time >= NOW() - INTERVAL '4 weeks'
               ORDER BY pair, time DESC""",
            list(PAIRS),
        )

    if not rows:
        await update.message.reply_text("No weekly data available yet.")
        return

    seen = set()
    lines = ["<b>Weekly Bias (W1)</b>"]
    for r in rows:
        if r["pair"] in seen:
            continue
        seen.add(r["pair"])
        last  = float(r["last_close"] or 0)
        avg   = float(r["avg_close"] or 0)
        if avg and last > avg * 1.001:
            bias, arrow = "bullish", "🔼"
        elif avg and last < avg * 0.999:
            bias, arrow = "bearish", "🔽"
        else:
            bias, arrow = "neutral", "➖"
        lines.append(f"{arrow} {r['pair']}: {bias.capitalize()}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_dd_override(update, context) -> None:
    """
    /dd_override <stage>  — force drawdown stage (0-3). Pro+ only.
    """
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _PRO_PLANS:
            await update.message.reply_text(
                _upgrade_text("/dd_override", "pro"), parse_mode="HTML"
            )
            return

        args = context.args or []
        if not args:
            await update.message.reply_text("Usage: /dd_override <0|1|2|3>")
            return

        try:
            stage = int(args[0])
            if stage not in (0, 1, 2, 3):
                raise ValueError
        except ValueError:
            await update.message.reply_text("Stage must be 0, 1, 2, or 3.")
            return

        await db.execute(
            "UPDATE risk_state SET drawdown_stage=$1, updated_at=NOW() "
            "WHERE user_id=$2::uuid",
            stage, user["id"],
        )
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
            user["id"], "risk_change", f"drawdown_stage forced to {stage} via telegram",
        )

    stage_label = _DD_STAGE_NAME.get(stage, str(stage))
    await update.message.reply_text(
        f"⚠️ DD stage overridden to <b>{stage_label}</b>.", parse_mode="HTML"
    )


async def cmd_bridge_status(update, context) -> None:
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _TRADER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/bridge_status", "trader"), parse_mode="HTML"
            )
            return

        row = await db.fetchrow(
            "SELECT trading_paused, last_heartbeat, failover_count "
            "FROM bridge_state LIMIT 1"
        )

    if not row:
        await update.message.reply_text("No bridge state data available.")
        return

    paused    = row["trading_paused"]
    icon      = "🔴" if paused else "🟢"
    heartbeat = row["last_heartbeat"]
    hb_str    = heartbeat.strftime("%Y-%m-%d %H:%M UTC") if heartbeat else "never"

    text = (
        f"<b>Bridge Status</b>\n"
        f"State:         {icon} {'paused' if paused else 'active'}\n"
        f"Last heartbeat: {hb_str}\n"
        f"Failovers:     {row['failover_count'] or 0}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_pairs(update, context) -> None:
    """
    /pairs              — list active/inactive pairs
    /pairs EURUSD on    — enable a pair
    /pairs EURUSD off   — disable a pair
    """
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan, active_pairs FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _PRO_PLANS:
            await update.message.reply_text(
                _upgrade_text("/pairs", "pro"), parse_mode="HTML"
            )
            return

        raw = user["active_pairs"]
        pairs: dict = json.loads(raw) if isinstance(raw, str) else (raw or {})

        args = context.args or []
        if args:
            if len(args) < 2 or args[1].lower() not in ("on", "off"):
                await update.message.reply_text(
                    "Usage: /pairs EURUSD on  or  /pairs EURUSD off"
                )
                return

            symbol = args[0].upper().replace("/", "")
            # normalise stored key format (may include slash like EUR/USD)
            key = next((k for k in pairs if k.replace("/", "") == symbol), None)
            if key is None:
                # add as new key matching stored format (no slash)
                key = symbol
            pairs[key] = args[1].lower() == "on"
            await db.execute(
                "UPDATE users SET active_pairs=$1::jsonb, updated_at=NOW() WHERE id=$2::uuid",
                json.dumps(pairs), user["id"],
            )
            await db.execute(
                "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
                user["id"], "settings_change",
                f"pair {key} set to {'enabled' if pairs[key] else 'disabled'} via telegram",
            )
            state = "enabled ✅" if pairs[key] else "disabled ⚫"
            await update.message.reply_text(
                f"<b>{key}</b> {state}.", parse_mode="HTML"
            )
            return

    lines = ["<b>Trading Pairs</b>"]
    for pair, enabled in sorted(pairs.items()):
        icon = "✅" if enabled else "⚫"
        lines.append(f"{icon} {pair}")
    lines.append("\n<i>Toggle: /pairs EURUSD on  or  /pairs EURUSD off</i>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_setsl(update, context) -> None:
    """
    /setsl          — show current SL override
    /setsl 25       — set SL override to 25 pips for next signal
    /setsl clear    — remove override (use AI default)
    """
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan, sl_override_pips FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _PRO_PLANS:
            await update.message.reply_text(
                _upgrade_text("/setsl", "pro"), parse_mode="HTML"
            )
            return

        args = context.args or []
        if not args:
            current = user["sl_override_pips"]
            if current is None:
                msg = "No SL override set — using AI default."
            else:
                msg = f"Current SL override: <b>{float(current):.1f} pips</b>\nUse /setsl clear to remove."
            await update.message.reply_text(msg, parse_mode="HTML")
            return

        if args[0].lower() == "clear":
            await db.execute(
                "UPDATE users SET sl_override_pips=NULL, updated_at=NOW() WHERE id=$1::uuid",
                user["id"],
            )
            await db.execute(
                "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
                user["id"], "settings_change", "SL override cleared via telegram",
            )
            await update.message.reply_text("✅ SL override cleared — AI default will be used.")
            return

        try:
            pips = float(args[0])
            if not (1 <= pips <= 500):
                raise ValueError
        except ValueError:
            await update.message.reply_text("Pips must be a number between 1 and 500.")
            return

        await db.execute(
            "UPDATE users SET sl_override_pips=$1, updated_at=NOW() WHERE id=$2::uuid",
            pips, user["id"],
        )
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
            user["id"], "settings_change", f"SL override set to {pips} pips via telegram",
        )
        await update.message.reply_text(
            f"✅ SL override set to <b>{pips:.1f} pips</b> for the next signal.", parse_mode="HTML"
        )


async def cmd_api_key(update, context) -> None:
    """
    /api_key        — show current API key (masked)
    /api_key rotate — generate a new key (invalidates old one)
    """
    tg_id = update.effective_user.id
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan, api_key FROM users WHERE telegram_chat_id=$1", tg_id
        )
        if not user or user["plan"] not in _ELITE_PLANS:
            await update.message.reply_text(
                _upgrade_text("/api_key", "elite"), parse_mode="HTML"
            )
            return

        args = context.args or []
        if args and args[0].lower() == "rotate":
            new_key = secrets.token_hex(32)
            await db.execute(
                "UPDATE users SET api_key=$1, updated_at=NOW() WHERE id=$2::uuid",
                new_key, user["id"],
            )
            await db.execute(
                "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
                user["id"], "settings_change", "API key rotated via telegram",
            )
            await update.message.reply_text(
                f"🔑 New API key generated:\n<code>{new_key}</code>\n\n"
                "<i>Save it now — this is the only time it will be shown in full.</i>",
                parse_mode="HTML",
            )
            return

        key = user["api_key"]
        if not key:
            await update.message.reply_text(
                "No API key yet. Use /api_key rotate to generate one."
            )
            return

        masked = key[:6] + "•" * (len(key) - 10) + key[-4:]
        await update.message.reply_text(
            f"🔑 Your API key: <code>{masked}</code>\n\n"
            "Use /api_key rotate to generate a new key.",
            parse_mode="HTML",
        )
