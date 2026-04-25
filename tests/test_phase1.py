"""
tests/test_phase1.py — Phase 1 quality gate tests.

Tests 1–3 require a live TimescaleDB instance and are skipped automatically
when the database is not reachable (CI / local-without-Docker). Run them
after `docker compose up -d && python -m database.init_db`.

Tests 4–5 use mocked dependencies and always run.
"""

import os
import time
import uuid
from datetime import timedelta, timezone, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from dotenv import load_dotenv

load_dotenv()

# ── DB availability ────────────────────────────────────────────────────────────

def _db_conn():
    """Return a psycopg2 connection or None if TimescaleDB is not reachable."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "trading_ai"),
            user=os.getenv("DB_USER", "trading_app"),
            password=os.getenv("DB_PASSWORD", ""),
            sslmode=os.getenv("DB_SSLMODE", "prefer"),
            connect_timeout=3,
        )
        conn.autocommit = False
        return conn
    except Exception:
        return None


_db_available = _db_conn() is not None

requires_db = pytest.mark.skipif(
    not _db_available,
    reason="TimescaleDB not reachable — start docker compose and run init_db first",
)


# ══════════════════════════════════════════════════════════════════════════════
# Test 1 — Hypertables with correct chunk intervals
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
def test_hypertables_exist_with_correct_intervals():
    """
    All four TimescaleDB hypertables must exist with the chunk intervals
    defined in Technical Docs Chapter 6:
        ohlc_m15      → 1 month
        ohlc_h4       → 6 months
        ohlc_w1       → 2 years
        feature_store → 1 month
    """
    conn = _db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT hypertable_name, time_interval::text "
                "FROM timescaledb_information.dimensions "
                "ORDER BY hypertable_name"
            )
            rows = {r[0]: r[1] for r in cur.fetchall()}
    finally:
        conn.close()

    expected = {
        "ohlc_m15":      "30 days",
        "ohlc_h4":       "180 days",
        "ohlc_w1":       "720 days",
        "feature_store": "30 days",
    }

    missing = [name for name in expected if name not in rows]
    assert not missing, f"Missing hypertables: {missing}. Found: {list(rows)}"

    for name, expected_interval in expected.items():
        actual = rows[name]
        assert expected_interval in actual or actual in expected_interval, (
            f"{name}: expected time_interval containing '{expected_interval}', got '{actual}'"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Test 2 — REFRESH MATERIALIZED VIEW CONCURRENTLY
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
def test_materialized_views_refresh_concurrently():
    """
    All three materialized views must support CONCURRENT refresh.
    This requires a UNIQUE index on each view (materialized_views.sql).
    Fails with 'ERROR: could not create unique index' if the unique index
    is missing, confirming the correction in Master Review §3.5 was applied.
    """
    views = ("mv_daily_pnl", "mv_rolling_performance", "mv_performance_by_pair")
    conn = _db_conn()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            for view in views:
                cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}")
    finally:
        conn.autocommit = False
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# Test 3 — RLS isolation: user B cannot see user A's rows
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
def test_rls_user_a_rows_invisible_to_user_b():
    """
    After inserting a trade for user_a, querying the trades table with
    app.current_user_id = user_b must return zero rows (RLS policy).

    If the connecting role is a PostgreSQL superuser (typical in Docker dev
    where POSTGRES_USER=trading_app), we create a throwaway non-superuser role
    so FORCE ROW LEVEL SECURITY is honoured.
    """
    import psycopg2

    conn = _db_conn()
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())

    try:
        # ── Insert test data as the connecting role (bypasses RLS if superuser) ──
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (id, email, password_hash, referral_code) "
                "VALUES (%s, %s, 'x', %s)",
                (user_a, f"testa_{user_a[:8]}@test.invalid", f"T-{user_a[:6].upper()}")
            )
            cur.execute(
                "INSERT INTO users (id, email, password_hash, referral_code) "
                "VALUES (%s, %s, 'x', %s)",
                (user_b, f"testb_{user_b[:8]}@test.invalid", f"T-{user_b[:6].upper()}")
            )
            cur.execute(
                "INSERT INTO trades (user_id, pair, direction, lot_size, "
                "entry_price, entry_time, status) "
                "VALUES (%s::uuid, 'EURUSD', 'buy', 0.01, 1.1000, NOW(), 'open')",
                (user_a,)
            )
        conn.commit()

        # ── Check if the session role is a superuser ──────────────────────────
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            )
            row = cur.fetchone()
            is_superuser = row[0] if row else False

        if is_superuser:
            # Create a minimal non-superuser test role so FORCE ROW LEVEL SECURITY
            # applies. SET SESSION AUTHORIZATION from a superuser session doesn't
            # require a password.
            with conn.cursor() as cur:
                cur.execute(
                    "DO $$ BEGIN "
                    "  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rls_tester') THEN "
                    "    CREATE ROLE rls_tester NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE; "
                    "  END IF; "
                    "END $$"
                )
                cur.execute("GRANT SELECT ON trades TO rls_tester")
                cur.execute("GRANT EXECUTE ON FUNCTION current_user_id() TO rls_tester")
            conn.commit()

            # Switch role, open a transaction, set RLS context to user_b
            with conn.cursor() as cur:
                cur.execute("SET SESSION AUTHORIZATION rls_tester")
            with conn.cursor() as cur:
                cur.execute("BEGIN")
                cur.execute("SET LOCAL app.current_user_id = %s", (user_b,))
                cur.execute("SELECT COUNT(*) FROM trades")
                count_all = cur.fetchone()[0]
                cur.execute("ROLLBACK")
            with conn.cursor() as cur:
                cur.execute("RESET SESSION AUTHORIZATION")
            conn.commit()

        else:
            # Non-superuser connection: FORCE ROW LEVEL SECURITY applies directly.
            with conn.cursor() as cur:
                cur.execute("BEGIN")
                cur.execute("SET LOCAL app.current_user_id = %s", (user_b,))
                cur.execute("SELECT COUNT(*) FROM trades")
                count_all = cur.fetchone()[0]
                cur.execute("ROLLBACK")

        assert count_all == 0, (
            f"RLS FAILURE: querying as user_b returned {count_all} row(s); "
            f"user_a's trade must not be visible"
        )

    finally:
        # Clean up test data (as the original superuser role)
        try:
            conn.rollback()  # ensure no open transaction before setting autocommit
        except Exception:
            pass
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM trades WHERE user_id = %s::uuid OR user_id = %s::uuid",
                (user_a, user_b)
            )
            cur.execute(
                "DELETE FROM users WHERE id = %s::uuid OR id = %s::uuid",
                (user_a, user_b)
            )
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# Test 4 — Stripe webhook updates plan within 5 seconds
# ══════════════════════════════════════════════════════════════════════════════

class _MockDb:
    """Minimal async DB mock for webhook and auth endpoint tests."""

    def __init__(self, fetchrow_result=None):
        self._fetchrow_result = fetchrow_result
        self.plan_updates: list[str] = []

    async def fetchrow(self, query, *args):
        return self._fetchrow_result

    async def execute(self, query, *args):
        if "UPDATE users SET plan" in query:
            self.plan_updates.append(args[0])  # first param = new_plan


def _make_client(mock_db: _MockDb):
    """Return a TestClient with get_db overridden by mock_db."""
    from fastapi.testclient import TestClient
    from main import app
    from database.connection import get_db

    async def _override():
        yield mock_db

    app.dependency_overrides[get_db] = _override
    return TestClient(app, raise_server_exceptions=True)


def test_stripe_webhook_updates_plan_within_5_seconds():
    """
    POST /billing/webhook with a subscription.created event must:
      1. return HTTP 200
      2. update the user's plan column in the DB
      3. complete within 5 seconds (billing quality gate)
    """
    from database.connection import get_db

    user_id = str(uuid.uuid4())
    customer_id = "cus_test_" + uuid.uuid4().hex[:8]
    price_id    = "price_trader_test"

    fake_user  = {"id": user_id, "plan": "community"}
    mock_db    = _MockDb(fetchrow_result=fake_user)

    fake_event = {
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id":       "sub_test_" + uuid.uuid4().hex[:8],
                "customer": customer_id,
                "status":   "active",
                "items":    {"data": [{"price": {"id": price_id}}]},
            }
        },
    }

    client = _make_client(mock_db)

    try:
        with (
            patch("stripe.Webhook.construct_event", return_value=fake_event),
            patch("api.billing.settings") as mock_settings,
        ):
            mock_settings.stripe_price_starter      = ""
            mock_settings.stripe_price_trader       = price_id
            mock_settings.stripe_price_pro          = ""
            mock_settings.stripe_price_elite        = ""
            mock_settings.stripe_webhook_secret     = "whsec_test"

            start    = time.perf_counter()
            response = client.post(
                "/billing/webhook",
                content=b'{"type":"customer.subscription.created"}',
                headers={
                    "Stripe-Signature": "t=1,v1=fakesig",
                    "Content-Type": "application/json",
                },
            )
            elapsed = time.perf_counter() - start

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        assert elapsed < 5.0, (
            f"Webhook took {elapsed:.3f}s — must complete within 5 seconds"
        )
        assert mock_db.plan_updates, (
            "Plan UPDATE was never executed — billing._apply_plan_change not reached"
        )
        assert mock_db.plan_updates[0] == "trader", (
            f"Expected plan='trader', got '{mock_db.plan_updates[0]}'"
        )

    finally:
        from main import app
        app.dependency_overrides.pop(get_db, None)


# ══════════════════════════════════════════════════════════════════════════════
# Test 5 — JWT lifecycle: issue, expiry, and refresh
# ══════════════════════════════════════════════════════════════════════════════

def test_jwt_issued_expires_correctly_refresh_works():
    """
    5a. _build_token produces a decodable JWT with the correct sub/email/plan/type.
    5b. _issue_pair returns distinct access and refresh tokens.
    5c. An access token with a 1-second TTL is rejected after it expires.
    5d. Supplying a refresh token where an access token is required → 401.
    5e. POST /auth/refresh with a valid refresh token returns a new token pair
        reflecting the current plan from the DB.
    """
    from jose import jwt as jose_jwt, JWTError
    from api.auth import _build_token, _issue_pair, get_current_user
    from config import settings
    from database.connection import get_db

    # Ensure a JWT secret is set for the test run
    if not settings.jwt_secret:
        settings.jwt_secret = "test-secret-key-phase1-quality-gate"

    uid   = str(uuid.uuid4())
    email = "quality@gate.test"
    plan  = "trader"

    # ── 5a: token structure ────────────────────────────────────────────────────
    access = _build_token(uid, email, plan, "access", timedelta(minutes=60))
    payload = jose_jwt.decode(access, settings.jwt_secret, algorithms=[settings.jwt_algorithm])

    assert payload["sub"]   == uid,      f"sub mismatch: {payload['sub']}"
    assert payload["email"] == email,    f"email mismatch: {payload['email']}"
    assert payload["plan"]  == plan,     f"plan mismatch: {payload['plan']}"
    assert payload["type"]  == "access", f"type mismatch: {payload['type']}"

    exp_in = payload["exp"] - payload["iat"]
    assert 3500 <= exp_in <= 3700, (
        f"access token TTL {exp_in}s outside expected 60-minute window"
    )

    # ── 5b: _issue_pair produces both tokens ───────────────────────────────────
    pair = _issue_pair(uid, email, plan)

    assert pair.access_token  != pair.refresh_token, "access and refresh tokens must differ"
    assert pair.user_id == uid
    assert pair.email   == email
    assert pair.plan    == plan

    acc_payload  = jose_jwt.decode(pair.access_token,  settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    ref_payload  = jose_jwt.decode(pair.refresh_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])

    assert acc_payload["type"] == "access",  "access_token must have type='access'"
    assert ref_payload["type"] == "refresh", "refresh_token must have type='refresh'"

    # ── 5c: expired token is rejected ─────────────────────────────────────────
    expired = _build_token(uid, email, plan, "access", timedelta(seconds=-1))
    with pytest.raises(JWTError):
        jose_jwt.decode(expired, settings.jwt_secret, algorithms=[settings.jwt_algorithm])

    # ── 5d: refresh token rejected by get_current_user ────────────────────────
    import asyncio
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=pair.refresh_token)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_current_user(creds))
    assert exc_info.value.status_code == 401

    # ── 5e: /auth/refresh endpoint returns a new token pair ───────────────────
    new_plan  = "pro"
    mock_user = {"id": uid, "email": email, "plan": new_plan}
    mock_db   = _MockDb(fetchrow_result=mock_user)
    client    = _make_client(mock_db)

    try:
        response = client.post(
            "/auth/refresh",
            json={"refresh_token": pair.refresh_token},
        )
        assert response.status_code == 200, (
            f"Expected 200 from /auth/refresh, got {response.status_code}: {response.text}"
        )

        data = response.json()
        assert "access_token"  in data, "response missing access_token"
        assert "refresh_token" in data, "response missing refresh_token"
        assert data["plan"]    == new_plan, (
            f"Expected refreshed plan='{new_plan}', got '{data['plan']}'"
        )

        # Verify the returned access token is valid and carries the updated plan
        new_payload = jose_jwt.decode(
            data["access_token"], settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        assert new_payload["plan"] == new_plan
        assert new_payload["type"] == "access"

    finally:
        from main import app as _app
        _app.dependency_overrides.pop(get_db, None)


# ── Allow running directly ────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
