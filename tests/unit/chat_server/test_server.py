"""Tests for chat-server/src/server.py — FastAPI endpoints: /health, /chat, error codes."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from shared.modules.api.chat_response import ChatResponse


@pytest.fixture()
def app_with_mocks():
    """Import and configure the FastAPI app with mocked dependencies."""
    with patch("server.MCPClientManager") as mock_mgr_cls, \
         patch("server.ClaudeLLMClient") as mock_llm_cls, \
         patch("server.ChatUseCase") as mock_uc_cls:

        mock_mgr = MagicMock()
        mock_mgr.initialize = AsyncMock()
        mock_mgr_cls.return_value = mock_mgr

        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        mock_uc = MagicMock()
        mock_uc.execute = AsyncMock(return_value=ChatResponse(answer="Test reply"))
        mock_uc_cls.return_value = mock_uc

        import server

        # Manually wire app.state since ASGITransport doesn't trigger lifespan
        server.app.state.chat_use_case = mock_uc
        server.app.state.timeout = 120

        yield server.app, mock_uc


@pytest.fixture()
async def client(app_with_mocks):
    app, _ = app_with_mocks
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture()
def mock_use_case(app_with_mocks):
    _, mock_uc = app_with_mocks
    return mock_uc


class TestHealth:
    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestChat:
    async def test_valid_chat_request(self, client, mock_use_case):
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

    async def test_generic_error_returns_500(self, client, mock_use_case):
        mock_use_case.execute = AsyncMock(side_effect=RuntimeError("unexpected"))
        resp = await client.post("/chat", json={
            "messages": [{"role": "user", "content": "hi"}]
        })
        assert resp.status_code == 500

    async def test_timeout_returns_504(self, app_with_mocks):
        app, mock_uc = app_with_mocks

        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(10)
            return ChatResponse(answer="done")

        mock_uc.execute = slow_execute
        app.state.timeout = 0.1

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/chat", json={
                "messages": [{"role": "user", "content": "hi"}]
            })
        assert resp.status_code == 504

    async def test_chat_with_tool_calls(self, client, mock_use_case):
        mock_use_case.execute = AsyncMock(return_value=ChatResponse(
            answer="Found data",
            tool_calls=[{"tool": "get_schema", "arguments": {}}],
        ))
        resp = await client.post("/chat", json={
            "messages": [{"role": "user", "content": "analyze"}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tool_calls"]) == 1

    async def test_multiple_messages(self, client, mock_use_case):
        resp = await client.post("/chat", json={
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
                {"role": "user", "content": "what data do you have?"},
            ]
        })
        assert resp.status_code == 200
