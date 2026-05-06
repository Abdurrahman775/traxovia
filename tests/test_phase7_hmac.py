"""
tests/test_phase7_hmac.py — Improvement 3.4: HMAC-SHA256 bridge signing.

Four tests:
  1. Valid signature is correctly constructed (correct HMAC digest)
  2. Expired timestamp (>30 s) is detectable as stale
  3. Wrong signature is detectable as invalid
  4. heartbeat_check() attaches X-Signature / X-Timestamp headers to the httpx call

Tests 1-3 verify the signing/verification logic directly — no mock bridge needed.
Test 4 mocks httpx and inspects the headers bridge_watchdog passes.
"""

from __future__ import annotations

import hmac
import hashlib
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Pre-mock dependencies absent on Linux ─────────────────────────────────────
for _mod in ("database", "database.connection", "notifications", "notifications.telegram_handler"):
    sys.modules.setdefault(_mod, MagicMock())

from core.execution_engine.bridge_watchdog import sign_request, heartbeat_check

# ── Shared test helpers ────────────────────────────────────────────────────────

_TEST_KEY = "test-hmac-secret-32chars-padded!!"


def _verify(method: str, path: str, headers: dict, key: str, body: str = "") -> tuple[bool, str]:
    """
    Replicate the bridge's HMAC verification logic.
    Returns (valid, reason).
    """
    ts_str = headers.get("X-Timestamp", "")
    sig    = headers.get("X-Signature", "")
    hdr_key = headers.get("X-Api-Key", "")

    if hdr_key != key:
        return False, "wrong_key"
    try:
        age = abs(int(time.time()) - int(ts_str))
    except ValueError:
        return False, "bad_timestamp"
    if age > 30:
        return False, "expired"

    expected = hmac.new(key.encode(), (method.upper() + path + ts_str + body).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False, "bad_signature"
    return True, "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Valid signature passes verification
# ═══════════════════════════════════════════════════════════════════════════════

def test_valid_signature_passes_verification():
    """
    sign_request() must produce headers that pass HMAC verification.
    """
    import os
    with patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": _TEST_KEY}):
        headers = sign_request("GET", "/health")

    valid, reason = _verify("GET", "/health", headers, _TEST_KEY)
    assert valid, f"Valid signed request must pass verification, got reason={reason!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Expired timestamp rejected with 401
# ═══════════════════════════════════════════════════════════════════════════════

def test_expired_timestamp_returns_401():
    """
    A timestamp 60 seconds in the past must be rejected as expired (age > 30 s).
    """
    ts  = str(int(time.time()) - 60)
    msg = ("GET/health" + ts).encode()
    sig = hmac.new(_TEST_KEY.encode(), msg, hashlib.sha256).hexdigest()
    headers = {"X-Api-Key": _TEST_KEY, "X-Timestamp": ts, "X-Signature": sig}

    valid, reason = _verify("GET", "/health", headers, _TEST_KEY)
    assert not valid,          "Expired timestamp must fail verification"
    assert reason == "expired", f"Expected reason='expired', got {reason!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Wrong signature rejected with 403
# ═══════════════════════════════════════════════════════════════════════════════

def test_wrong_signature_returns_403():
    """
    A fresh timestamp with a tampered X-Signature must fail verification.
    """
    import os
    with patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": _TEST_KEY}):
        headers = sign_request("GET", "/health")
    headers["X-Signature"] = "deadbeef" * 8  # wrong value

    valid, reason = _verify("GET", "/health", headers, _TEST_KEY)
    assert not valid,                  "Wrong signature must fail verification"
    assert reason == "bad_signature",  f"Expected reason='bad_signature', got {reason!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — heartbeat_check sends signed headers
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_heartbeat_check_uses_signed_headers():
    """
    heartbeat_check() must pass X-Api-Key, X-Timestamp, and X-Signature
    to the httpx GET /health call.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__  = AsyncMock(return_value=None)

    with patch("core.execution_engine.bridge_watchdog.httpx.AsyncClient", return_value=cm):
        await heartbeat_check()

    assert mock_client.get.called, "heartbeat_check must call httpx client.get()"

    call    = mock_client.get.call_args
    headers = call.kwargs.get("headers") or (call.args[1] if len(call.args) > 1 else {})

    assert "X-Signature" in headers, f"Must include X-Signature, got: {list(headers)}"
    assert "X-Timestamp" in headers, f"Must include X-Timestamp, got: {list(headers)}"
    assert "X-Api-Key"   in headers, f"Must include X-Api-Key, got: {list(headers)}"
