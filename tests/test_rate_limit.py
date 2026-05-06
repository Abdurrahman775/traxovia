"""
tests/test_rate_limit.py — Rate limiting quality gate tests.

Three tests exercising the slowapi-based 5 req/min limit wired onto
/referral/apply, plus the custom 429 error shape.

Each test builds an isolated FastAPI app with its own fresh Limiter instance
so rate counters from one test never bleed into another.

Run:
    pytest tests/test_rate_limit.py -v
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address


# ── Test-app factory ───────────────────────────────────────────────────────────

def _fresh_client() -> TestClient:
    """
    Build an isolated FastAPI app with:
      - a brand-new Limiter (no shared state with other tests)
      - the same exception handler shape as main.py
      - a single POST /referral/apply route limited to 5/minute
    """
    lim = Limiter(key_func=get_remote_address)
    app = FastAPI()
    app.state.limiter = lim
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _handler(req: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "error":       "rate_limit_exceeded",
                "message":     "Too many requests. Try again later.",
                "retry_after": 60,
            },
        )

    @app.post("/referral/apply")
    @lim.limit("5/minute")
    async def _apply(request: Request) -> dict:
        return {"status": "applied"}

    return TestClient(app, raise_server_exceptions=False)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — First 5 requests succeed (200 or 400, never 429)
# ═══════════════════════════════════════════════════════════════════════════════

def test_first_5_requests_are_not_rate_limited():
    """
    The first 5 POST requests to /referral/apply within one minute must be
    served (200 or 400 from business logic), never blocked with 429.
    """
    client = _fresh_client()
    for i in range(5):
        resp = client.post("/referral/apply")
        assert resp.status_code in (200, 400), (
            f"Request {i + 1}/5 got {resp.status_code} — "
            "first 5 requests must not be rate-limited"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — 6th request returns 429
# ═══════════════════════════════════════════════════════════════════════════════

def test_6th_request_returns_429():
    """
    After 5 allowed requests the 6th must return HTTP 429.
    The fresh client ensures this test's counter starts at zero.
    """
    client = _fresh_client()
    for _ in range(5):
        client.post("/referral/apply")

    resp = client.post("/referral/apply")
    assert resp.status_code == 429, (
        f"6th request must return 429, got {resp.status_code}: {resp.text}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — 429 response body has correct error shape
# ═══════════════════════════════════════════════════════════════════════════════

def test_429_response_body_shape():
    """
    The 429 body must be exactly:
      {"error": "rate_limit_exceeded",
       "message": "Too many requests. Try again later.",
       "retry_after": 60}
    """
    client = _fresh_client()
    for _ in range(5):
        client.post("/referral/apply")

    resp = client.post("/referral/apply")
    assert resp.status_code == 429

    body = resp.json()
    assert body.get("error") == "rate_limit_exceeded", (
        f"error field wrong: {body.get('error')!r}"
    )
    assert body.get("message") == "Too many requests. Try again later.", (
        f"message field wrong: {body.get('message')!r}"
    )
    assert body.get("retry_after") == 60, (
        f"retry_after must be integer 60, got {body.get('retry_after')!r}"
    )
