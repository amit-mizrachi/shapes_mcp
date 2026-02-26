"""Tests for chat-server/src/server.py — FastAPI endpoints: /health, /chat, error codes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from shared.modules.api.chat_response import ChatResponse


@pytest.fixture()
def app_with_mocks():
    """Import and configure the FastAPI app with mocked dependencies."""
    with patch("server.MCPClientManager") as mock_mgr_cls, \
         patch("server.ClaudeLLMClient") as mock_llm_cls, \
         patch("server.ChatOrchestrator") as mock_orch_cls:

        mock_mgr = MagicMock()
        mock_mgr.initialize = AsyncMock()
        mock_mgr_cls.return_value = mock_mgr

        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        mock_orch = MagicMock()
        mock_orch.chat = AsyncMock(return_value=ChatResponse(answer="Test reply"))
        mock_orch_cls.return_value = mock_orch

        import server
        server.mcp_manager = mock_mgr
        server.orchestrator = mock_orch

        yield server.app, mock_orch


@pytest.fixture()
async def client(app_with_mocks):
    app, _ = app_with_mocks
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture()
def mock_orchestrator(app_with_mocks):
    _, mock_orch = app_with_mocks
    return mock_orch


class TestHealth:
    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestChat:
    async def test_valid_chat_request(self, client, mock_orchestrator):
        resp = await client.post("/chat", json={
            "messages": [{"role": "user", "content": "hello"}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "Test reply"
        assert data["tool_calls"] == []

    async def test_empty_messages_returns_422(self, client):
        resp = await client.post("/chat", json={"messages": []})
        assert resp.status_code == 422

    async def test_missing_messages_returns_422(self, client):
        resp = await client.post("/chat", json={})
        assert resp.status_code == 422

    async def test_message_too_long_returns_422(self, client):
        long_content = "x" * 5001
        resp = await client.post("/chat", json={
            "messages": [{"role": "user", "content": long_content}]
        })
        assert resp.status_code == 422

    async def test_connection_error_returns_503(self, client, mock_orchestrator):
        mock_orchestrator.chat = AsyncMock(side_effect=ConnectionError("MCP down"))
        resp = await client.post("/chat", json={
            "messages": [{"role": "user", "content": "hi"}]
        })
        assert resp.status_code == 503

    async def test_rate_limit_error_returns_429(self, client, mock_orchestrator):
        mock_orchestrator.chat = AsyncMock(side_effect=Exception("rate_limit_error 429"))
        resp = await client.post("/chat", json={
            "messages": [{"role": "user", "content": "hi"}]
        })
        assert resp.status_code == 429

    async def test_generic_error_returns_500(self, client, mock_orchestrator):
        mock_orchestrator.chat = AsyncMock(side_effect=RuntimeError("unexpected"))
        resp = await client.post("/chat", json={
            "messages": [{"role": "user", "content": "hi"}]
        })
        assert resp.status_code == 500

    async def test_chat_with_tool_calls(self, client, mock_orchestrator):
        mock_orchestrator.chat = AsyncMock(return_value=ChatResponse(
            answer="Found data",
            tool_calls=[{"tool": "get_schema", "result": "ok"}],
        ))
        resp = await client.post("/chat", json={
            "messages": [{"role": "user", "content": "analyze"}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tool_calls"]) == 1

    async def test_multiple_messages(self, client, mock_orchestrator):
        resp = await client.post("/chat", json={
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
                {"role": "user", "content": "what data do you have?"},
            ]
        })
        assert resp.status_code == 200
