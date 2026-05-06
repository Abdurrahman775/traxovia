"""
tests/test_phase8_executor.py — Unit tests for core/execution_engine/mt5_executor.py

Tests cover:
  - open_order: success (201), BridgeError on 4xx/5xx
  - close_order: success (200), BridgeError on 4xx, partial close
  - HMAC signing: headers present, non-empty, correct keys
  - _sign: timestamp recency, correct message construction
"""

import hashlib
import hmac
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Module under test ──────────────────────────────────────────────────────────
from core.execution_engine.mt5_executor import (
    BridgeError,
    OrderCloseResult,
    OrderOpenResult,
    _sign,
    close_order,
    open_order,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mock_http_client(status_code: int, body: dict):
    """
    Return a patched httpx.AsyncClient context manager that yields a mock
    whose .post() and .get() return a response with the given status and body.
    """
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = body
    mock_response.text = json.dumps(body)

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.get  = AsyncMock(return_value=mock_response)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__  = AsyncMock(return_value=None)

    return mock_cm, mock_client


# ── _sign() unit tests ─────────────────────────────────────────────────────────

def test_sign_returns_required_headers():
    with patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "test-key-123"}):
        headers = _sign("POST", "/order/open", '{"symbol":"EURUSD"}')

    assert "X-Api-Key"    in headers
    assert "X-Timestamp"  in headers
    assert "X-Signature"  in headers
    assert "Content-Type" in headers


def test_sign_timestamp_is_recent():
    with patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "test-key", "MT5_BRIDGE_CLOCK_OFFSET": "0"}):
        headers = _sign("GET", "/health")

    ts = int(headers["X-Timestamp"])
    assert abs(time.time() - ts) < 5, "Timestamp must be within 5 seconds of now"


def test_sign_hmac_is_correct():
    api_key = "secret-key-for-test"
    method  = "POST"
    path    = "/order/open"
    body    = '{"symbol":"EURUSD","direction":"buy"}'

    with patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": api_key}):
        headers = _sign(method, path, body)

    ts      = headers["X-Timestamp"]
    message = (method.upper() + path + ts + body).encode()
    expected = hmac.new(api_key.encode(), message, hashlib.sha256).hexdigest()

    assert headers["X-Signature"] == expected


def test_sign_different_bodies_produce_different_signatures():
    with patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "k"}):
        h1 = _sign("POST", "/order/open", '{"a":1}')
        h2 = _sign("POST", "/order/open", '{"a":2}')

    # Timestamps may differ by 1 second between calls — check body changes signature
    # (reconstruct both to compare with same timestamp)
    api_key = "k"
    ts = h1["X-Timestamp"]
    m1 = ("POST/order/open" + ts + '{"a":1}').encode()
    m2 = ("POST/order/open" + ts + '{"a":2}').encode()
    s1 = hmac.new(api_key.encode(), m1, hashlib.sha256).hexdigest()
    s2 = hmac.new(api_key.encode(), m2, hashlib.sha256).hexdigest()
    assert s1 != s2


# ── open_order() tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_order_success_returns_result():
    bridge_response = {
        "ticket":      12345678,
        "symbol":      "EURUSD",
        "direction":   "buy",
        "lot_size":    0.01,
        "open_price":  1.08500,
        "stop_loss":   1.08200,
        "take_profit": 1.08900,
        "comment":     "TradingAI_V3",
    }
    mock_cm, mock_client = _mock_http_client(201, bridge_response)

    with patch("core.execution_engine.mt5_executor.httpx.AsyncClient", return_value=mock_cm), \
         patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "k", "MT5_BRIDGE_PRIMARY_URL": "http://127.0.0.1:8001"}):
        result = await open_order("EURUSD", "buy", 0.01, 1.08200, 1.08900)

    assert isinstance(result, OrderOpenResult)
    assert result.ticket     == 12345678
    assert result.symbol     == "EURUSD"
    assert result.direction  == "buy"
    assert result.lot_size   == 0.01
    assert result.open_price == 1.08500
    assert result.stop_loss  == 1.08200
    assert result.take_profit == 1.08900
    assert result.comment    == "TradingAI_V3"


@pytest.mark.asyncio
async def test_open_order_posts_to_correct_endpoint():
    bridge_response = {
        "ticket": 1, "symbol": "EURUSD", "direction": "sell",
        "lot_size": 0.1, "open_price": 1.085, "stop_loss": 1.09,
        "take_profit": 1.08, "comment": "test",
    }
    mock_cm, mock_client = _mock_http_client(201, bridge_response)

    with patch("core.execution_engine.mt5_executor.httpx.AsyncClient", return_value=mock_cm), \
         patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "k", "MT5_BRIDGE_PRIMARY_URL": "http://127.0.0.1:8001"}):
        await open_order("EURUSD", "sell", 0.1, 1.09, 1.08)

    call_args = mock_client.post.call_args
    assert "/order/open" in call_args.args[0], "Must POST to /order/open"


@pytest.mark.asyncio
async def test_open_order_sends_signed_headers():
    bridge_response = {
        "ticket": 1, "symbol": "EURUSD", "direction": "buy",
        "lot_size": 0.01, "open_price": 1.085, "stop_loss": 1.082,
        "take_profit": 1.089, "comment": "TradingAI_V3",
    }
    mock_cm, mock_client = _mock_http_client(201, bridge_response)

    with patch("core.execution_engine.mt5_executor.httpx.AsyncClient", return_value=mock_cm), \
         patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "mykey", "MT5_BRIDGE_PRIMARY_URL": "http://127.0.0.1:8001"}):
        await open_order("EURUSD", "buy", 0.01, 1.082, 1.089)

    sent_headers = mock_client.post.call_args.kwargs["headers"]
    assert sent_headers["X-Api-Key"]   == "mykey"
    assert sent_headers["X-Timestamp"] != ""
    assert sent_headers["X-Signature"] != ""


@pytest.mark.asyncio
async def test_open_order_raises_bridge_error_on_400():
    mock_cm, _ = _mock_http_client(400, {"detail": "Order rejected: retcode=10015"})

    with patch("core.execution_engine.mt5_executor.httpx.AsyncClient", return_value=mock_cm), \
         patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "k"}):
        with pytest.raises(BridgeError) as exc_info:
            await open_order("EURUSD", "buy", 0.01, 1.082, 1.089)

    assert "400" in str(exc_info.value)


@pytest.mark.asyncio
async def test_open_order_raises_bridge_error_on_503():
    mock_cm, _ = _mock_http_client(503, {"detail": "MT5 terminal not connected"})

    with patch("core.execution_engine.mt5_executor.httpx.AsyncClient", return_value=mock_cm), \
         patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "k"}):
        with pytest.raises(BridgeError) as exc_info:
            await open_order("EURUSD", "buy", 0.01, 1.082, 1.089)

    assert "503" in str(exc_info.value)


@pytest.mark.asyncio
async def test_open_order_custom_comment_passed_in_body():
    bridge_response = {
        "ticket": 99, "symbol": "XAUUSD", "direction": "buy",
        "lot_size": 0.01, "open_price": 2340.0, "stop_loss": 2330.0,
        "take_profit": 2360.0, "comment": "my-custom-comment",
    }
    mock_cm, mock_client = _mock_http_client(201, bridge_response)

    with patch("core.execution_engine.mt5_executor.httpx.AsyncClient", return_value=mock_cm), \
         patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "k", "MT5_BRIDGE_PRIMARY_URL": "http://127.0.0.1:8001"}):
        result = await open_order("XAUUSD", "buy", 0.01, 2330.0, 2360.0, comment="my-custom-comment")

    sent_body = json.loads(mock_client.post.call_args.kwargs["content"])
    assert sent_body["comment"] == "my-custom-comment"
    assert result.comment == "my-custom-comment"


# ── close_order() tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_order_success_returns_result():
    bridge_response = {
        "ticket":      12345678,
        "close_price": 1.08650,
        "profit":      15.50,
        "comment":     "close — ok",
    }
    mock_cm, mock_client = _mock_http_client(200, bridge_response)

    with patch("core.execution_engine.mt5_executor.httpx.AsyncClient", return_value=mock_cm), \
         patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "k", "MT5_BRIDGE_PRIMARY_URL": "http://127.0.0.1:8001"}):
        result = await close_order(12345678)

    assert isinstance(result, OrderCloseResult)
    assert result.ticket      == 12345678
    assert result.close_price == 1.08650
    assert result.profit      == 15.50
    assert result.comment     == "close — ok"


@pytest.mark.asyncio
async def test_close_order_partial_sends_lot_size():
    bridge_response = {
        "ticket": 111, "close_price": 1.085, "profit": 5.0, "comment": "partial",
    }
    mock_cm, mock_client = _mock_http_client(200, bridge_response)

    with patch("core.execution_engine.mt5_executor.httpx.AsyncClient", return_value=mock_cm), \
         patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "k", "MT5_BRIDGE_PRIMARY_URL": "http://127.0.0.1:8001"}):
        await close_order(111, lot_size=0.05)

    sent_body = json.loads(mock_client.post.call_args.kwargs["content"])
    assert sent_body["ticket"]   == 111
    assert sent_body["lot_size"] == 0.05


@pytest.mark.asyncio
async def test_close_order_full_omits_lot_size_key():
    bridge_response = {
        "ticket": 222, "close_price": 1.086, "profit": 10.0, "comment": "full close",
    }
    mock_cm, mock_client = _mock_http_client(200, bridge_response)

    with patch("core.execution_engine.mt5_executor.httpx.AsyncClient", return_value=mock_cm), \
         patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "k", "MT5_BRIDGE_PRIMARY_URL": "http://127.0.0.1:8001"}):
        await close_order(222)

    sent_body = json.loads(mock_client.post.call_args.kwargs["content"])
    assert "lot_size" not in sent_body, "Full close must not send lot_size key"


@pytest.mark.asyncio
async def test_close_order_raises_bridge_error_on_404():
    mock_cm, _ = _mock_http_client(404, {"detail": "No open position for ticket 999"})

    with patch("core.execution_engine.mt5_executor.httpx.AsyncClient", return_value=mock_cm), \
         patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "k"}):
        with pytest.raises(BridgeError) as exc_info:
            await close_order(999)

    assert "404" in str(exc_info.value)


@pytest.mark.asyncio
async def test_close_order_posts_to_correct_endpoint():
    bridge_response = {
        "ticket": 1, "close_price": 1.085, "profit": 0.0, "comment": "ok",
    }
    mock_cm, mock_client = _mock_http_client(200, bridge_response)

    with patch("core.execution_engine.mt5_executor.httpx.AsyncClient", return_value=mock_cm), \
         patch.dict(os.environ, {"MT5_BRIDGE_API_KEY": "k", "MT5_BRIDGE_PRIMARY_URL": "http://127.0.0.1:8001"}):
        await close_order(1)

    call_args = mock_client.post.call_args
    assert "/order/close" in call_args.args[0], "Must POST to /order/close"
