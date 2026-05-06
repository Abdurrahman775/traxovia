"""
tests/test_phase7_routes.py — Auth and plan-gate tests for Phase 7 API routes.

Four tests covering the three route files (signals, analytics, auditlog):

  1. No auth header         → 403  (HTTPBearer rejects missing token)
  2. Community plan         → 403  on GET  /signals
  3. Starter plan           → 403  on POST /signals/{id}/approve
  4. Community plan         → 403  on GET  /analytics/performance

Each test builds an isolated FastAPI app so dependency overrides never bleed
between tests.  The DB dependency is always mocked to avoid real DB connections.

Run:
    pytest tests/test_phase7_routes.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _mock_db() -> AsyncMock:
    """Minimal asyncpg connection mock — all methods return empty/zero."""
    db = AsyncMock()
    db.fetch    = AsyncMock(return_value=[])
    db.fetchrow = AsyncMock(return_value=None)
    db.fetchval = AsyncMock(return_value=0)
    db.execute  = AsyncMock(return_value=None)
    return db


def _make_client(user: dict | None = None) -> TestClient:
    """
    Build an isolated TestClient that includes all three Phase 7 routers.

    When *user* is provided, get_current_user is overridden to return it
    without touching the JWT stack.  When omitted, the real HTTPBearer
    dependency runs and will reject unauthenticated requests.

    get_db is always overridden so no real DB connection is attempted.
    """
    from api.routes.signals  import router as signals_router
    from api.routes.analytics import router as analytics_router
    from api.routes.auditlog  import router as auditlog_router
    from api.auth            import get_current_user
    from database.connection import get_db

    app = FastAPI()
    app.include_router(signals_router)
    app.include_router(analytics_router)
    app.include_router(auditlog_router)

    # Always mock the DB so tests never need a running PostgreSQL instance.
    db = _mock_db()
    async def _override_db():
        yield db
    app.dependency_overrides[get_db] = _override_db

    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user

    return TestClient(app, raise_server_exceptions=False)


def _user(plan: str) -> dict:
    return {
        "sub":   "00000000-0000-0000-0000-000000000001",
        "email": "test@example.com",
        "plan":  plan,
        "type":  "access",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Unauthenticated request is rejected
# ═══════════════════════════════════════════════════════════════════════════════

def test_unauthenticated_request_rejected():
    """
    GET /signals without an Authorization header must be rejected.
    FastAPI's HTTPBearer returns 403 when no bearer token is present.
    """
    client = _make_client()   # no user override — real HTTPBearer runs
    resp   = client.get("/signals")
    assert resp.status_code in (401, 403), (
        f"Missing token must be rejected with 401 or 403, got {resp.status_code}: {resp.text}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Community plan cannot view signals
# ═══════════════════════════════════════════════════════════════════════════════

def test_community_plan_cannot_view_signals():
    """
    GET /signals with a community-plan user must return 403.
    Signal access requires Starter plan or above.
    """
    client = _make_client(user=_user("community"))
    resp   = client.get("/signals")
    assert resp.status_code == 403, (
        f"Community plan must be blocked from /signals, got {resp.status_code}: {resp.text}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Starter plan cannot approve signals
# ═══════════════════════════════════════════════════════════════════════════════

def test_starter_plan_cannot_approve_signals():
    """
    POST /signals/{id}/approve with a starter-plan user must return 403.
    Signal approval requires Trader plan or above.
    """
    client = _make_client(user=_user("starter"))
    resp   = client.post("/signals/00000000-0000-0000-0000-000000000099/approve")
    assert resp.status_code == 403, (
        f"Starter plan must be blocked from approving signals, "
        f"got {resp.status_code}: {resp.text}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Community plan cannot access analytics
# ═══════════════════════════════════════════════════════════════════════════════

def test_community_plan_cannot_access_analytics():
    """
    GET /analytics/performance with a community-plan user must return 403.
    Analytics access requires Starter plan or above.
    """
    client = _make_client(user=_user("community"))
    resp   = client.get("/analytics/performance")
    assert resp.status_code == 403, (
        f"Community plan must be blocked from analytics, "
        f"got {resp.status_code}: {resp.text}"
    )
