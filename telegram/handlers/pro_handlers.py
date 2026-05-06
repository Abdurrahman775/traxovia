"""
telegram/handlers/pro_handlers.py — Pro+ advanced commands.

Commands:
  /risk           — show/update risk parameters
  /mode           — switch trading mode (auto/manual)
  /weekly         — weekly confluence bias summary
  /dd_override    — override drawdown stage (emergency use)
  /bridge_status  — detailed bridge diagnostics
"""
from __future__ import annotations

from telegram.handlers import _PRO_PLANS, _TRADER_PLANS, _bot_db, _upgrade_text, _DD_STAGE_NAME


async def cmd_risk(update, context) -> None:
    """
    /risk                           — show current risk params
    /risk max_risk_pct=1.5          — update a single param
    """
    tg_id = str(update.effective_user.id)
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_id=$1", tg_id
        )
        if not user or user["plan"] not in _PRO_PLANS:
            await update.message.reply_text(
                _upgrade_text("/risk", "pro"), parse_mode="HTML"
            )
            return

        args = context.args or []
        if args:
            # Parse key=value pairs
            updates = {}
            allowed = {"max_risk_pct", "max_daily_dd_pct", "max_total_dd_pct", "pause_on_dd_stage"}
            for arg in args:
                if "=" not in arg:
                    continue
                k, _, v = arg.partition("=")
                if k in allowed:
                    try:
                        updates[k] = float(v) if k != "pause_on_dd_stage" else int(v)
                    except ValueError:
                        await update.message.reply_text(f"Invalid value for {k}: {v!r}")
                        return

            if not updates:
                await update.message.reply_text(
                    "Usage: /risk max_risk_pct=1.5 max_daily_dd_pct=3.0"
                )
                return

            for col, val in updates.items():
                await db.execute(
                    f"UPDATE risk_profiles SET {col}=$1, updated_at=NOW() "
                    "WHERE user_id=$2::uuid",
                    val, user["id"],
                )
            await db.execute(
                "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
                user["id"], "risk_change", f"updated risk params via telegram: {updates}",
            )

            await update.message.reply_text(
                f"✅ Risk params updated: {updates}", parse_mode="HTML"
            )
            return

        row = await db.fetchrow(
            "SELECT max_risk_pct, max_daily_dd_pct, max_total_dd_pct, pause_on_dd_stage "
            "FROM risk_profiles WHERE user_id=$1::uuid",
            user["id"],
        )

    if not row:
        await update.message.reply_text("No risk profile found.")
        return

    text = (
        f"<b>Risk Parameters</b>\n"
        f"Max risk/trade:  {row['max_risk_pct']:.2f}%\n"
        f"Daily DD limit:  {row['max_daily_dd_pct']:.2f}%\n"
        f"Total DD limit:  {row['max_total_dd_pct']:.2f}%\n"
        f"Pause at stage:  {row['pause_on_dd_stage']}\n\n"
        "<i>To update: /risk max_risk_pct=1.5</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_mode(update, context) -> None:
    """
    /mode auto    — enable full automation
    /mode manual  — switch to manual approval
    """
    tg_id = str(update.effective_user.id)
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_id=$1", tg_id
        )
        if not user or user["plan"] not in _PRO_PLANS:
            await update.message.reply_text(
                _upgrade_text("/mode", "pro"), parse_mode="HTML"
            )
            return

        args = context.args or []
        if not args or args[0] not in ("auto", "manual"):
            await update.message.reply_text("Usage: /mode auto  or  /mode manual")
            return

        mode = args[0]
        await db.execute(
            "UPDATE mt5_accounts SET trading_mode=$1, updated_at=NOW() "
            "WHERE user_id=$2::uuid",
            mode, user["id"],
        )
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
            user["id"], "risk_change", f"trading mode changed to {mode} via telegram",
        )

    icon = "🤖" if mode == "auto" else "🖐"
    await update.message.reply_text(f"{icon} Trading mode set to <b>{mode}</b>.", parse_mode="HTML")


async def cmd_weekly(update, context) -> None:
    tg_id = str(update.effective_user.id)
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_id=$1", tg_id
        )
        if not user or user["plan"] not in _PRO_PLANS:
            await update.message.reply_text(
                _upgrade_text("/weekly", "pro"), parse_mode="HTML"
            )
            return

        rows = await db.fetch(
            "SELECT pair, bias, key_level, confluence_score "
            "FROM weekly_bias WHERE user_id=$1::uuid "
            "ORDER BY confluence_score DESC NULLS LAST",
            user["id"],
        )

    if not rows:
        await update.message.reply_text("No weekly bias data available.")
        return

    lines = ["<b>Weekly Confluence</b>"]
    for r in rows:
        arrow = "🔼" if r["bias"] == "bullish" else "🔽" if r["bias"] == "bearish" else "➖"
        lines.append(
            f"{arrow} {r['pair']}  score:{r['confluence_score'] or 0:.0f}  "
            f"key:{r['key_level'] or 'n/a'}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_dd_override(update, context) -> None:
    """
    /dd_override <stage>  — force drawdown stage (0-3). Pro+ only.
    """
    tg_id = str(update.effective_user.id)
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_id=$1", tg_id
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
            "UPDATE mt5_accounts SET dd_stage=$1, updated_at=NOW() "
            "WHERE user_id=$2::uuid",
            stage, user["id"],
        )
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1::uuid,$2,$3)",
            user["id"], "risk_change", f"dd_stage forced to {stage} via telegram",
        )

    stage_label = _DD_STAGE_NAME.get(stage, str(stage))
    await update.message.reply_text(
        f"⚠️ DD stage overridden to <b>{stage_label}</b>.", parse_mode="HTML"
    )


async def cmd_bridge_status(update, context) -> None:
    tg_id = str(update.effective_user.id)
    async with _bot_db() as db:
        user = await db.fetchrow(
            "SELECT id, plan FROM users WHERE telegram_id=$1", tg_id
        )
        if not user or user["plan"] not in _TRADER_PLANS:
            await update.message.reply_text(
                _upgrade_text("/bridge_status", "trader"), parse_mode="HTML"
            )
            return

        rows = await db.fetch(
            "SELECT bridge_type, status, latency_ms, checked_at "
            "FROM bridge_health ORDER BY checked_at DESC LIMIT 4"
        )

    if not rows:
        await update.message.reply_text("No bridge health data available.")
        return

    lines = ["<b>Bridge Diagnostics</b>"]
    for r in rows:
        icon = "🟢" if r["status"] == "ok" else "🔴"
        lat  = f"{r['latency_ms']:.0f}ms" if r["latency_ms"] else "n/a"
        lines.append(f"{icon} {r['bridge_type']}: {r['status']}  {lat}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")
