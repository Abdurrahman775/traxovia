"""
api/routes/settings.py — User settings read/update.
"""
import json
from typing import Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from database.connection import get_db, set_rls_user
from api.auth import get_current_user

router = APIRouter(tags=["settings"])


class SettingsPatch(BaseModel):
    # trading tab
    trading_mode:           str   | None = None
    news_blocking:          bool  | None = None
    friday_cutoff:          bool  | None = None
    copy_trade_enabled:     bool  | None = None
    # risk tab
    base_risk_pct:          float | None = None
    risk_max_pct:           float | None = None
    risk_max_drawdown_pct:  float | None = None
    risk_daily_pct:         float | None = None
    # pairs tab
    active_pairs:           dict[str, Any] | None = None
    # mt5 tab
    mt5_accounts:           list[Any] | None = None
    # notifications tab
    notification_prefs:     dict[str, Any] | None = None
    # other
    is_paper_mode:          bool  | None = None
    max_trades_per_day:     int   | None = None


@router.get("/settings")
async def get_settings(user=Depends(get_current_user), db=Depends(get_db)):
    await set_rls_user(db, user["sub"])
    row = await db.fetchrow(
        """SELECT base_risk_pct, is_paper_mode, max_trades_per_day,
                  plan, email, trading_mode, news_blocking, friday_cutoff,
                  copy_trade_enabled, risk_max_pct, risk_max_drawdown_pct,
                  risk_daily_pct, active_pairs, mt5_accounts, notification_prefs
           FROM users WHERE id=$1""",
        user["sub"],
    )
    if not row:
        return {}
    d = dict(row)

    for key in ("active_pairs", "mt5_accounts", "notification_prefs"):
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except (ValueError, TypeError):
                d[key] = {} if key != "mt5_accounts" else []

    for key in ("base_risk_pct", "risk_max_pct", "risk_max_drawdown_pct", "risk_daily_pct"):
        if d.get(key) is not None:
            d[key] = float(d[key])

    # Include bot username so Telegram tab can show it without an admin-only call
    try:
        cfg = await db.fetchrow(
            "SELECT telegram_bot_token FROM bot_config WHERE id=1"
        )
        token = cfg["telegram_bot_token"] if cfg else ""
        if token:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            data = resp.json()
            if data.get("ok"):
                d["telegram_bot_username"] = data["result"]["username"]
    except Exception:
        pass

    return d


@router.patch("/settings")
async def update_settings(
    body: SettingsPatch,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    await set_rls_user(db, user["sub"])
    updates, params, i = [], [], 1

    scalar_fields = [
        ("trading_mode",          body.trading_mode),
        ("news_blocking",         body.news_blocking),
        ("friday_cutoff",         body.friday_cutoff),
        ("copy_trade_enabled",    body.copy_trade_enabled),
        ("base_risk_pct",         body.base_risk_pct),
        ("risk_max_pct",          body.risk_max_pct),
        ("risk_max_drawdown_pct", body.risk_max_drawdown_pct),
        ("risk_daily_pct",        body.risk_daily_pct),
        ("is_paper_mode",         body.is_paper_mode),
        ("max_trades_per_day",    body.max_trades_per_day),
    ]
    for col, val in scalar_fields:
        if val is not None:
            updates.append(f"{col}=${i}"); params.append(val); i += 1

    for col, val in [
        ("active_pairs",       body.active_pairs),
        ("mt5_accounts",       body.mt5_accounts),
        ("notification_prefs", body.notification_prefs),
    ]:
        if val is not None:
            updates.append(f"{col}=${i}::jsonb")
            params.append(json.dumps(val)); i += 1

    if updates:
        params.append(user["sub"])
        await db.execute(
            f"UPDATE users SET {', '.join(updates)}, updated_at=NOW() WHERE id=${i}",
            *params,
        )
    return {"status": "updated"}
