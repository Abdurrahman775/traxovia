"""
tests/test_phase7.py — Phase 7 quality gate tests.

Six tests covering plan gating, trial start, referral fraud, analytics MV
usage, audit log writing, and community drop formatting.

All tests are self-contained: DB and external services are always mocked.

Run:
    pytest tests/test_phase7.py -v
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── PTB stub ───────────────────────────────────────────────────────────────────
# The project's telegram/ directory shadows python-telegram-bot, so we inject a
# fake Bot attribute that supports await so community_drops.post_result_drop()
# works without a real Telegram install.
import telegram as _tg_pkg
_tg_pkg.Bot = MagicMock()  # type: ignore[attr-defined]

# ── Pre-import real API/DB modules at module level ─────────────────────────────
# tests/test_phase7_hmac.py replaces sys.modules['database.connection'] with a
# MagicMock at its own import time.  pytest imports ALL test files before running
# any test, so by the time our test functions execute, database.connection may
# already be poisoned.  Importing these objects here — while this module is still
# being collected first — ensures we hold references to the real functions.
# _api_client() must use these cached references as dependency-override keys so
# FastAPI matches the same objects that route handlers captured at their import.
from database.connection       import get_db           as _real_get_db
from api.auth                  import get_current_user as _real_get_current_user
from api.auth                  import router as _auth_router, TokenResponse
from api.routes.analytics      import router as _analytics_router
from api.routes.auditlog       import router as _audit_router
from api.routes.signals        import router as _signals_router
from api.routes.trial          import router as _trial_router
from api.routes.referral       import router as _referral_router


# ── Shared DB mock ─────────────────────────────────────────────────────────────

def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.fetch    = AsyncMock(return_value=[])
    db.fetchrow = AsyncMock(return_value=None)
    db.fetchval = AsyncMock(return_value=None)
    db.execute  = AsyncMock(return_value=None)
    return db


def _api_client(routers: list, user: dict | None, db: AsyncMock) -> TestClient:
    """Build an isolated FastAPI TestClient with mocked auth and DB."""
    app = FastAPI()
    for r in routers:
        app.include_router(r)

    async def _db_override():
        yield db

    # Use the pre-imported real objects as keys — these match what route
    # handlers bound at their own import time.
    app.dependency_overrides[_real_get_db] = _db_override
    if user is not None:
        app.dependency_overrides[_real_get_current_user] = lambda: user

    return TestClient(app, raise_server_exceptions=False)


# ── Telegram test helpers ──────────────────────────────────────────────────────

def _make_update(text: str = "/status") -> MagicMock:
    u = MagicMock()
    u.effective_user.id = 555444333
    u.message.text = text
    u.message.reply_text = AsyncMock()
    return u


def _make_ctx(args: list[str] | None = None) -> MagicMock:
    c = MagicMock()
    c.args = args or []
    return c


@asynccontextmanager
async def _mock_bot_db_ctx(db: AsyncMock):
    yield db


# ══════════════════════════════════════════════════════════════════════════════
# Test 1 — All 5 plan tiers gate correctly
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_all_plan_tiers_gate_correctly():
    """
    Verify that plan gates accept and reject correctly across all 5 tiers:

      Community : /status → blocked  |  /signals  → blocked
      Starter   : /status → allowed  |  /approve  → blocked
      Trader    : /approve → allowed |  /mode     → blocked
      Pro       : /mode   → allowed
      Elite     : /status, /approve, /mode all allowed

    "Blocked" means the reply contains the upgrade sentinel "⬆️".
    "Allowed" means "⬆️" is absent from the reply.
    """
    from telegram.handlers.status_handlers import cmd_status, cmd_signals
    from telegram.handlers.trade_handlers  import cmd_approve
    from telegram.handlers.pro_handlers    import cmd_mode

    def _db(plan: str, extra_rows: list | None = None) -> AsyncMock:
        db = _mock_db()
        rows = [{"id": "uid-t1", "plan": plan}] + (extra_rows or [])
        db.fetchrow = AsyncMock(side_effect=rows)
        return db

    def _replied(upd: MagicMock) -> str:
        return upd.message.reply_text.call_args[0][0]

    # ── Community: /status blocked ────────────────────────────────
    upd = _make_update("/status")
    with patch("telegram.handlers.status_handlers._bot_db",
               lambda: _mock_bot_db_ctx(_db("community"))):
        await cmd_status(upd, _make_ctx())
    assert "⬆️" in _replied(upd), \
        f"Community /status should be blocked, got: {_replied(upd)!r}"

    # ── Community: /signals blocked ───────────────────────────────
    upd = _make_update("/signals")
    with patch("telegram.handlers.status_handlers._bot_db",
               lambda: _mock_bot_db_ctx(_db("community"))):
        await cmd_signals(upd, _make_ctx())
    assert "⬆️" in _replied(upd), \
        f"Community /signals should be blocked, got: {_replied(upd)!r}"

    # ── Starter: /status allowed ──────────────────────────────────
    # cmd_status runs 3 fetchrows inside _bot_db: user, account, bridge.
    # Both account and bridge execute before the "if not account" early-return.
    upd = _make_update("/status")
    with patch("telegram.handlers.status_handlers._bot_db",
               lambda: _mock_bot_db_ctx(_db("starter", [None, None]))):
        await cmd_status(upd, _make_ctx())
    assert "⬆️" not in _replied(upd), \
        f"Starter /status should be allowed, got: {_replied(upd)!r}"

    # ── Starter: /approve blocked ─────────────────────────────────
    upd = _make_update("/approve_abcd1234")
    upd.message.text = "/approve_abcd1234"
    with patch("telegram.handlers.trade_handlers._bot_db",
               lambda: _mock_bot_db_ctx(_db("starter"))):
        await cmd_approve(upd, _make_ctx())
    assert "⬆️" in _replied(upd), \
        f"Starter /approve should be blocked, got: {_replied(upd)!r}"

    # ── Trader: /approve allowed ──────────────────────────────────
    # Second fetchrow returns the matching signal row
    signal_row = {"id": "sig-00000001", "status": "pending"}
    upd = _make_update("/approve_abcd1234")
    upd.message.text = "/approve_abcd1234"
    with patch("telegram.handlers.trade_handlers._bot_db",
               lambda: _mock_bot_db_ctx(_db("trader", [signal_row]))):
        await cmd_approve(upd, _make_ctx())
    assert "⬆️" not in _replied(upd), \
        f"Trader /approve should be allowed, got: {_replied(upd)!r}"

    # ── Trader: /mode blocked ─────────────────────────────────────
    upd = _make_update("/mode auto")
    with patch("telegram.handlers.pro_handlers._bot_db",
               lambda: _mock_bot_db_ctx(_db("trader"))):
        await cmd_mode(upd, _make_ctx(args=["auto"]))
    assert "⬆️" in _replied(upd), \
        f"Trader /mode should be blocked, got: {_replied(upd)!r}"

    # ── Pro: /mode allowed ────────────────────────────────────────
    upd = _make_update("/mode auto")
    with patch("telegram.handlers.pro_handlers._bot_db",
               lambda: _mock_bot_db_ctx(_db("pro"))):
        await cmd_mode(upd, _make_ctx(args=["auto"]))
    assert "⬆️" not in _replied(upd), \
        f"Pro /mode should be allowed, got: {_replied(upd)!r}"

    # ── Elite: /status, /approve, /mode all allowed ───────────────
    upd_status = _make_update("/status")
    with patch("telegram.handlers.status_handlers._bot_db",
               lambda: _mock_bot_db_ctx(_db("elite", [None, None]))):
        await cmd_status(upd_status, _make_ctx())
    assert "⬆️" not in _replied(upd_status), \
        f"Elite /status should be allowed, got: {_replied(upd_status)!r}"

    upd_approve = _make_update("/approve_abcd1234")
    upd_approve.message.text = "/approve_abcd1234"
    with patch("telegram.handlers.trade_handlers._bot_db",
               lambda: _mock_bot_db_ctx(_db("elite", [signal_row]))):
        await cmd_approve(upd_approve, _make_ctx())
    assert "⬆️" not in _replied(upd_approve), \
        f"Elite /approve should be allowed, got: {_replied(upd_approve)!r}"

    upd_mode = _make_update("/mode auto")
    with patch("telegram.handlers.pro_handlers._bot_db",
               lambda: _mock_bot_db_ctx(_db("elite"))):
        await cmd_mode(upd_mode, _make_ctx(args=["auto"]))
    assert "⬆️" not in _replied(upd_mode), \
        f"Elite /mode should be allowed, got: {_replied(upd_mode)!r}"


# ══════════════════════════════════════════════════════════════════════════════
# Test 2 — Trial starts correctly
# ══════════════════════════════════════════════════════════════════════════════

def test_trial_starts_correctly():
    """
    POST /trial/start for a community user must:
      1. Return 200 with paper_mode=True
      2. Issue an UPDATE setting plan='trial' and is_paper_mode=TRUE
      3. INSERT into audit_log
    """
    community_user = {
        "sub":              "00000000-0000-0000-0000-000000000010",
        "id":               "00000000-0000-0000-0000-000000000010",
        "email":            "trial@example.com",
        "plan":             "community",
        "trial_expires_at": None,
        "type":             "access",
    }
    db     = _mock_db()
    # fetchrow returns no existing trial
    db.fetchrow = AsyncMock(return_value={"trial_expires_at": None})
    client = _api_client([_trial_router], community_user, db)

    resp = client.post("/trial/start")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body.get("paper_mode") is True, (
        f"paper_mode must be True in response, got: {body}"
    )

    # Collect every SQL string passed to db.execute
    all_sql = " ".join(c.args[0] for c in db.execute.call_args_list if c.args)

    assert "plan='trial'" in all_sql, (
        f"plan='trial' not found in execute calls.\nSQL dump:\n{all_sql}"
    )
    assert "is_paper_mode=TRUE" in all_sql, (
        f"is_paper_mode=TRUE not found in execute calls.\nSQL dump:\n{all_sql}"
    )
    assert "audit_log" in all_sql, (
        f"audit_log INSERT not found in execute calls.\nSQL dump:\n{all_sql}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Test 3 — Referral fraud check — same /24 subnet blocked
# ══════════════════════════════════════════════════════════════════════════════

def test_referral_same_subnet_blocked():
    """
    POST /referral/apply must return 400 when the new user's IP and the
    referrer's signup_ip share the same /24 subnet (FIX-5a fraud check).
    """
    # The referred user — no existing referrer, no cooldown
    applicant = {
        "sub":         "00000000-0000-0000-0000-000000000020",
        "id":          "00000000-0000-0000-0000-000000000020",
        "email":       "new@example.com",
        "plan":        "community",
        "referred_by": None,
        "type":        "access",
    }

    # Referrer row returned from DB — signup_ip in same /24 as the request IP
    referrer_row = {
        "id":                 "00000000-0000-0000-0000-000000000021",
        "signup_ip":          "10.0.1.5",   # same /24 as 10.0.1.x
        "stripe_customer_id": None,
    }

    db = _mock_db()
    # First fetchrow: check applicant's referred_by (None = not yet referred)
    # Second fetchrow: look up referrer by code
    db.fetchrow = AsyncMock(side_effect=[
        {"referred_by": None},   # applicant check
        referrer_row,            # referrer lookup
    ])

    # Build the app with slowapi wired up (referral router requires it)
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    from fastapi.responses import JSONResponse

    fresh_limiter = Limiter(key_func=lambda r: "10.0.1.100")
    app = FastAPI()
    app.state.limiter = fresh_limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _rl_handler(req, exc):
        return JSONResponse(status_code=429, content={"error": "rate_limit_exceeded"})

    app.include_router(_referral_router)

    async def _db_override():
        yield db

    # Use pre-imported real objects as override keys (avoids sys.modules poison)
    app.dependency_overrides[_real_get_db] = _db_override
    app.dependency_overrides[_real_get_current_user] = lambda: applicant

    client = TestClient(app, raise_server_exceptions=False)

    # Patch get_remote_address inside referral.py to return a same-/24 IP
    with patch("api.routes.referral.get_remote_address",
               return_value="10.0.1.100"):
        resp = client.post("/referral/apply?code=TRADER-ABCDEF")

    assert resp.status_code == 400, (
        f"Same-subnet referral must return 400, got {resp.status_code}: {resp.text}"
    )
    detail = resp.json().get("detail", "")
    assert "network" in detail.lower() or "subnet" in detail.lower(), (
        f"Error message must mention network/subnet fraud, got: {detail!r}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Test 4 — Analytics endpoint uses materialized view
# ══════════════════════════════════════════════════════════════════════════════

def test_analytics_endpoint_uses_materialized_view():
    """
    GET /analytics/performance must:
      1. Complete in under 1 second (no full-table scan)
      2. Query mv_rolling_performance — NOT the raw trades table
    """
    starter_user = {
        "sub":   "00000000-0000-0000-0000-000000000030",
        "email": "analytics@example.com",
        "plan":  "starter",
        "type":  "access",
    }

    db = _mock_db()
    # Return None → handler returns zero-value defaults without error
    db.fetchrow = AsyncMock(return_value=None)

    client = _api_client([_analytics_router], starter_user, db)

    t0 = time.perf_counter()
    resp = client.get("/analytics/performance")
    elapsed = time.perf_counter() - t0

    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    assert elapsed < 1.0, f"Response took too long ({elapsed:.3f}s) — possible full scan"

    # Inspect the SQL that was passed to fetchrow
    assert db.fetchrow.called, "db.fetchrow was never called"
    query = db.fetchrow.call_args[0][0]  # first positional arg is the SQL string

    assert "mv_rolling_performance" in query, (
        f"Query must read from mv_rolling_performance, got:\n{query}"
    )
    # "trades" appears in column names (total_trades, best_trade_r…) — check
    # the FROM clause specifically to confirm no raw trades table is queried.
    import re
    from_tables = re.findall(r'\bfrom\s+(\w+)', query.lower())
    assert "trades" not in from_tables, (
        f"FROM clause must name mv_rolling_performance, not raw trades table. "
        f"Found: {from_tables}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Test 5 — Audit log records login event
# ══════════════════════════════════════════════════════════════════════════════

def test_audit_log_records_login_event():
    """
    POST /auth/login must INSERT into audit_log with action='login'.
    GET  /audit must return that entry with action='login'.

    Part A: login route — verify db.execute receives the login audit entry.
    Part B: audit route — verify the response contains a login-action entry.
    """
    USER_ID = "00000000-0000-0000-0000-000000000040"

    # ── Part A: login writes audit entry ────────────────────────────────────
    db_login = _mock_db()
    db_login.fetchrow = AsyncMock(return_value={
        "id":            USER_ID,
        "email":         "login@example.com",
        "password_hash": "bcrypt-hash-placeholder",
        "plan":          "starter",
    })

    login_app = FastAPI()
    login_app.include_router(_auth_router)

    async def _db_login_override():
        yield db_login

    # Use pre-imported real get_db so the override key matches what auth.py bound
    login_app.dependency_overrides[_real_get_db] = _db_login_override
    login_client = TestClient(login_app, raise_server_exceptions=False)

    fake_tokens = TokenResponse(
        access_token="fake.access.token",
        refresh_token="fake.refresh.token",
        user_id=USER_ID,
        email="login@example.com",
        plan="starter",
    )

    with (
        patch("api.auth._pwd") as mock_pwd,
        patch("api.auth._issue_pair", return_value=fake_tokens),
    ):
        mock_pwd.verify = MagicMock(return_value=True)
        resp = login_client.post(
            "/auth/login",
            json={"email": "login@example.com", "password": "testpassword"},
        )

    assert resp.status_code == 200, f"Login failed: {resp.status_code}: {resp.text}"

    # Check that one execute call inserted into audit_log with action='login'
    login_audit_found = any(
        c.args
        and "audit_log" in c.args[0]
        and "login" in c.args  # 'login' is the $2 positional arg
        for c in db_login.execute.call_args_list
    )
    assert login_audit_found, (
        "db.execute must have been called with an audit_log INSERT containing action='login'.\n"
        f"Actual calls: {[c.args for c in db_login.execute.call_args_list]}"
    )

    # ── Part B: audit route returns the login entry ──────────────────────────
    login_entry = {
        "id":         "aud-00000001",
        "action":     "login",
        "detail":     "Login from testclient",
        "ip_address": "127.0.0.1",
        "user_agent": None,
        "created_at": datetime.utcnow().isoformat(),
    }

    db_audit = _mock_db()
    db_audit.fetch    = AsyncMock(return_value=[login_entry])
    db_audit.fetchval = AsyncMock(return_value=1)

    audit_user = {
        "sub":   USER_ID,
        "email": "login@example.com",
        "plan":  "starter",
        "type":  "access",
    }

    audit_client = _api_client([_audit_router], audit_user, db_audit)
    resp2 = audit_client.get("/audit")

    assert resp2.status_code == 200, f"GET /audit failed: {resp2.status_code}: {resp2.text}"

    entries = resp2.json().get("entries", [])
    assert any(e.get("action") == "login" for e in entries), (
        f"audit log response must contain a 'login' entry, got: {entries}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Test 6 — Community result drop posts correct format for a win trade
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_community_result_drop_win_trade():
    """
    post_result_drop with a winning trade (result_r=2.1) must:
      - Include the pair name
      - Include the direction (BUY)
      - Include +2.10R
      - Include the win emoji ✅
    """
    from telegram.community_drops import _format_result_drop, post_result_drop

    trade = {
        "pair":      "GBPUSD",
        "direction": "buy",
        "result_r":  2.1,
    }
    signal = {
        "regime":         "trending",
        "ai_probability": 0.88,
        "entry_price":    1.2750,
    }

    # ── Pure function check ────────────────────────────────────────
    msg = _format_result_drop(trade, signal)

    assert "GBPUSD"  in msg,          f"Pair missing: {msg!r}"
    assert "BUY"     in msg.upper(),  f"Direction missing: {msg!r}"
    assert "+2.10"   in msg,          f"+2.10R missing: {msg!r}"
    assert "✅"       in msg,          f"Win emoji ✅ missing: {msg!r}"

    # ── post_result_drop sends the formatted message via Bot ───────
    bot_instance = AsyncMock()
    bot_instance.send_message = AsyncMock()
    mock_bot_cls = MagicMock(return_value=bot_instance)

    # Inject the mock Bot into the project's telegram package so the lazy
    # `from telegram import Bot` inside post_result_drop resolves to it.
    _tg_pkg.Bot = mock_bot_cls

    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN":              "fake-token-12345",
        "TELEGRAM_COMMUNITY_CHANNEL_ID":   "-1001234567890",
    }):
        await post_result_drop(trade, signal)

    assert bot_instance.send_message.called, (
        "Bot.send_message was never called — post_result_drop did not send"
    )
    sent_kwargs = bot_instance.send_message.call_args.kwargs
    sent_text   = sent_kwargs.get("text", "")

    assert "GBPUSD" in sent_text, f"Pair missing from sent text: {sent_text!r}"
    assert "+2.10"  in sent_text, f"+2.10R missing from sent text: {sent_text!r}"
    assert "✅"      in sent_text, f"Win emoji ✅ missing from sent text: {sent_text!r}"
