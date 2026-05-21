"""
api/routes/settings.py — User settings read/update.
"""
import json
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database.connection import get_db, set_rls_user
from api.auth import get_current_user

router = APIRouter(tags=["settings"])


class SettingsPatch(BaseModel):
    # trading tab
    trading_mode:           str   | None = None
    trading_paused:         bool  | None = None
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

    # Strip passwords from mt5_accounts before sending to client
    if isinstance(d.get("mt5_accounts"), list):
        d["mt5_accounts"] = [
            {k: v for k, v in acc.items() if k != "password"}
            for acc in d["mt5_accounts"]
        ]

    for key in ("base_risk_pct", "risk_max_pct", "risk_max_drawdown_pct", "risk_daily_pct"):
        if d.get(key) is not None:
            d[key] = float(d[key])

    # Include bot username from cached column (set when admin tests the connection)
    try:
        cfg = await db.fetchrow(
            "SELECT telegram_bot_username FROM bot_config WHERE id=1"
        )
        if cfg and cfg["telegram_bot_username"]:
            d["telegram_bot_username"] = cfg["telegram_bot_username"]
    except Exception:
        pass

    # Include bridge_state.trading_paused so frontend reflects Telegram /pause
    try:
        bridge = await db.fetchrow("SELECT trading_paused FROM bridge_state LIMIT 1")
        d["trading_paused"] = bool(bridge["trading_paused"]) if bridge else False
    except Exception:
        d["trading_paused"] = False

    return d


_VALID_TRADING_MODES = {"signal_approval", "auto_trade", "paper"}

@router.patch("/settings")
async def update_settings(
    body: SettingsPatch,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    await set_rls_user(db, user["sub"])

    # ── Fetch user plan for server-side feature gating ────────────────────────
    row = await db.fetchrow("SELECT plan FROM users WHERE id=$1", user["sub"])
    plan = row["plan"] if row else "community"
    is_elite = plan == "elite"

    # ── Input validation ──────────────────────────────────────────────────────
    from fastapi import HTTPException
    if body.trading_mode is not None:
        if body.trading_mode not in _VALID_TRADING_MODES:
            raise HTTPException(400, f"Invalid trading_mode. Must be one of: {', '.join(_VALID_TRADING_MODES)}")
        if body.trading_mode == "auto_trade" and not is_elite:
            # auto_execute is a plan feature — fetch from plan_config
            feat = await db.fetchval(
                "SELECT features->>'auto_execute' FROM plan_config WHERE plan_id=$1", plan
            )
            if feat != "true":
                raise HTTPException(403, "Auto-execute trading requires a higher plan")

    if body.copy_trade_enabled is True and not is_elite:
        feat = await db.fetchval(
            "SELECT features->>'copy_trade' FROM plan_config WHERE plan_id=$1", plan
        )
        if feat != "true":
            raise HTTPException(403, "Copy Trade requires Trader plan or above")

    if body.base_risk_pct is not None and not (0.1 <= body.base_risk_pct <= 10):
        raise HTTPException(400, "base_risk_pct must be between 0.1 and 10")
    if body.risk_max_pct is not None and not (0.1 <= body.risk_max_pct <= 10):
        raise HTTPException(400, "risk_max_pct must be between 0.1 and 10")
    if body.risk_max_drawdown_pct is not None and not (1 <= body.risk_max_drawdown_pct <= 50):
        raise HTTPException(400, "risk_max_drawdown_pct must be between 1 and 50")
    if body.risk_daily_pct is not None and not (0.5 <= body.risk_daily_pct <= 20):
        raise HTTPException(400, "risk_daily_pct must be between 0.5 and 20")
    if body.max_trades_per_day is not None and not (1 <= body.max_trades_per_day <= 50):
        raise HTTPException(400, "max_trades_per_day must be between 1 and 50")

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
        ("notification_prefs", body.notification_prefs),
    ]:
        if val is not None:
            updates.append(f"{col}=${i}::jsonb")
            params.append(json.dumps(val)); i += 1

    # mt5_accounts: merge incoming accounts with stored ones to preserve passwords.
    # The GET endpoint strips passwords before sending to the client, so a PATCH
    # from the frontend may arrive without passwords for existing accounts.
    if body.mt5_accounts is not None:
        existing_raw = await db.fetchval(
            "SELECT mt5_accounts FROM users WHERE id=$1", user["sub"]
        )
        try:
            existing = json.loads(existing_raw) if isinstance(existing_raw, str) else (existing_raw or [])
        except Exception:
            existing = []
        # Build a map of existing passwords keyed by login+server
        existing_passwords = {
            (str(a.get("login", "")), str(a.get("server", ""))): a.get("password")
            for a in existing if isinstance(a, dict) and a.get("password")
        }
        merged = []
        for acc in body.mt5_accounts:
            if isinstance(acc, dict):
                key = (str(acc.get("login", "")), str(acc.get("server", "")))
                if not acc.get("password") and key in existing_passwords:
                    acc = {**acc, "password": existing_passwords[key]}
                merged.append(acc)
        updates.append(f"mt5_accounts=${i}::jsonb")
        params.append(json.dumps(merged)); i += 1

    if updates:
        params.append(user["sub"])
        await db.execute(
            f"UPDATE users SET {', '.join(updates)}, updated_at=NOW() WHERE id=${i}",
            *params,
        )

    # bridge_state.trading_paused mirrors Telegram /pause — update separately
    if body.trading_paused is not None:
        await db.execute(
            "INSERT INTO bridge_state (active_url, primary_url, standby_url, trading_paused)"
            " SELECT '','','',$1::boolean FROM (SELECT 1) t"
            " WHERE NOT EXISTS (SELECT 1 FROM bridge_state)",
            body.trading_paused,
        )
        await db.execute(
            "UPDATE bridge_state SET trading_paused=$1, updated_at=NOW()",
            body.trading_paused,
        )
        await db.execute(
            "UPDATE risk_state SET trading_allowed=$1, updated_at=NOW() WHERE user_id=$2",
            not body.trading_paused,
            user["sub"],
        )
        await db.execute(
            "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
            user["sub"],
            "risk_change",
            f"trading {'paused' if body.trading_paused else 'resumed'} via web dashboard",
        )

    return {"status": "updated"}


# ── Telegram linking ───────────────────────────────────────────────────────────

def _generate_token() -> str:
    """Generate a readable 8-char alphanumeric token, e.g. TRX-A3F9."""
    chars = [secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6)]
    return "TRX-" + "".join(chars)


@router.post("/settings/telegram/link-token")
async def generate_telegram_link_token(
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Generate a short-lived token the user sends to the bot via /link TOKEN."""
    await set_rls_user(db, user["sub"])

    token      = _generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    await db.execute(
        """UPDATE users
           SET telegram_link_token=$1, telegram_link_expires_at=$2, updated_at=NOW()
           WHERE id=$3""",
        token, expires_at, user["sub"],
    )
    return {
        "token":      token,
        "expires_at": expires_at.isoformat(),
        "expires_in": 900,  # seconds
    }


@router.get("/settings/telegram/status")
async def get_telegram_status(
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Return current Telegram link status for the logged-in user."""
    await set_rls_user(db, user["sub"])
    row = await db.fetchrow(
        "SELECT telegram_chat_id, telegram_username FROM users WHERE id=$1",
        user["sub"],
    )
    if not row or not row["telegram_chat_id"]:
        return {"linked": False, "telegram_chat_id": None, "telegram_username": None}
    return {
        "linked":            True,
        "telegram_chat_id":  row["telegram_chat_id"],
        "telegram_username": row["telegram_username"],
    }


@router.delete("/settings/telegram/unlink")
async def unlink_telegram(
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Unlink Telegram from the dashboard (same effect as /unlink in the bot)."""
    await set_rls_user(db, user["sub"])
    await db.execute(
        "UPDATE users SET telegram_chat_id=NULL, telegram_username=NULL, "
        "updated_at=NOW() WHERE id=$1",
        user["sub"],
    )
    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        user["sub"], "mt5_binding", "Telegram unlinked via dashboard",
    )
