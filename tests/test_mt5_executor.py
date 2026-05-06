"""
tests/test_mt5_executor.py — Unit tests for mt5_executor.py
Run: pytest tests/test_mt5_executor.py -v
"""

import json
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from core.execution_engine.mt5_executor import (
    MT5ExecutorError,
    OrderResult,
    CloseResult,
    open_order,
    close_order,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _mock_response(status: int, body: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


OPEN_RESP = {
    "ticket": 12345, "symbol": "EURUSD", "direction": "buy",
    "lot_size": 0.01, "open_price": 1.1000,
    "stop_loss": 1.0980, "take_profit": 1.1030, "comment": "TradingAI_V3",
}
CLOSE_RESP = {
    "ticket": 12345, "close_price": 1.1010, "profit": 1.0, "comment": "Request executed",
}


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_order_returns_order_result():
    with patch("core.execution_engine.mt5_executor._post",
               new_callable=AsyncMock,
               return_value=_mock_response(201, OPEN_RESP)):
        result = await open_order("EURUSD", "buy", 0.01, 1.0980, 1.1030)

    assert isinstance(result, OrderResult)
    assert result.ticket     == 12345
    assert result.symbol     == "EURUSD"
    assert result.direction  == "buy"
    assert result.open_price == 1.1000


@pytest.mark.asyncio
async def test_close_order_returns_close_result():
    with patch("core.execution_engine.mt5_executor._post",
               new_callable=AsyncMock,
               return_value=_mock_response(200, CLOSE_RESP)):
        result = await close_order(12345)

    assert isinstance(result, CloseResult)
    assert result.ticket      == 12345
    assert result.close_price == 1.1010
    assert result.profit      == 1.0


@pytest.mark.asyncio
async def test_open_order_raises_on_bridge_error():
    with patch("core.execution_engine.mt5_executor._post",
               new_callable=AsyncMock,
               return_value=_mock_response(400, {"detail": "AutoTrading disabled"})):
        with pytest.raises(MT5ExecutorError, match="AutoTrading disabled"):
            await open_order("EURUSD", "buy", 0.01, 1.0980, 1.1030)


@pytest.mark.asyncio
async def test_close_order_raises_on_bridge_error():
    with patch("core.execution_engine.mt5_executor._post",
               new_callable=AsyncMock,
               return_value=_mock_response(400, {"detail": "No open position"})):
        with pytest.raises(MT5ExecutorError, match="No open position"):
            await close_order(99999)


@pytest.mark.asyncio
async def test_open_order_raises_on_network_error():
    with patch("core.execution_engine.mt5_executor._post",
               new_callable=AsyncMock,
               side_effect=MT5ExecutorError("Bridge unreachable")):
        with pytest.raises(MT5ExecutorError, match="Bridge unreachable"):
            await open_order("EURUSD", "buy", 0.01, 1.0980, 1.1030)


@pytest.mark.asyncio
async def test_close_order_partial_passes_lot_size():
    """Partial close: lot_size is included in the request body."""
    captured = {}

    async def _fake_post(path, payload):
        captured["body"] = json.loads(payload)
        return _mock_response(200, CLOSE_RESP)

    with patch("core.execution_engine.mt5_executor._post", side_effect=_fake_post):
        await close_order(12345, lot_size=0.005)

    assert captured["body"]["lot_size"] == 0.005
    assert captured["body"]["ticket"]   == 12345
