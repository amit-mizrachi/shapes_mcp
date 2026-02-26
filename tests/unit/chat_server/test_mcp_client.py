"""Tests for chat-server/src/mcp_client/mcp_client.py — context manager, list_tools, call_tool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_client.mcp_client import MCPClient


class TestMCPClient:
    @pytest.fixture()
    def mock_streams(self):
        """Mock the streamable_http_client context manager."""
        read = AsyncMock()
        write = AsyncMock()
        get_url = MagicMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=(read, write, get_url))
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        return mock_cm

    @pytest.fixture()
    def mock_session(self):
        """Mock ClientSession."""
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.initialize = AsyncMock()
        return session

    async def test_context_manager_enter_exit(self, mock_streams, mock_session):
        with patch("mcp_client.mcp_client.streamable_http_client", return_value=mock_streams), \
             patch("mcp_client.mcp_client.ClientSession", return_value=mock_session):
            async with MCPClient("http://localhost:3001/mcp") as client:
                assert client._session is not None

    async def test_list_tools(self, mock_streams, mock_session):
        mock_tool = SimpleNamespace(
            name="get_schema",
            description="Get the schema",
            inputSchema={"type": "object"},
        )
        mock_session.list_tools = AsyncMock(
            return_value=SimpleNamespace(tools=[mock_tool])
        )

        with patch("mcp_client.mcp_client.streamable_http_client", return_value=mock_streams), \
             patch("mcp_client.mcp_client.ClientSession", return_value=mock_session):
            async with MCPClient("http://localhost:3001/mcp") as client:
                tools = await client.list_tools()

        assert len(tools) == 1
        assert tools[0]["name"] == "get_schema"
        assert tools[0]["description"] == "Get the schema"
        assert tools[0]["inputSchema"] == {"type": "object"}

    async def test_call_tool(self, mock_streams, mock_session):
        text_content = SimpleNamespace(text='{"data": []}')
        mock_session.call_tool = AsyncMock(
            return_value=SimpleNamespace(content=[text_content])
        )

        with patch("mcp_client.mcp_client.streamable_http_client", return_value=mock_streams), \
             patch("mcp_client.mcp_client.ClientSession", return_value=mock_session):
            async with MCPClient("http://localhost:3001/mcp") as client:
                result = await client.call_tool("select_rows", {"limit": 5})

        assert result == '{"data": []}'

    async def test_call_tool_multiple_content(self, mock_streams, mock_session):
        content1 = SimpleNamespace(text="line1")
        content2 = SimpleNamespace(text="line2")
        mock_session.call_tool = AsyncMock(
            return_value=SimpleNamespace(content=[content1, content2])
        )

        with patch("mcp_client.mcp_client.streamable_http_client", return_value=mock_streams), \
             patch("mcp_client.mcp_client.ClientSession", return_value=mock_session):
            async with MCPClient("http://localhost:3001/mcp") as client:
                result = await client.call_tool("test", {})

        assert result == "line1\nline2"

    async def test_call_tool_non_text_content(self, mock_streams, mock_session):
        content = SimpleNamespace(data="binary")  # No .text attribute
        mock_session.call_tool = AsyncMock(
            return_value=SimpleNamespace(content=[content])
        )

        with patch("mcp_client.mcp_client.streamable_http_client", return_value=mock_streams), \
             patch("mcp_client.mcp_client.ClientSession", return_value=mock_session):
            async with MCPClient("http://localhost:3001/mcp") as client:
                result = await client.call_tool("test", {})

        # Should fall back to str()
        assert "data=" in result or "binary" in result

    async def test_list_tools_empty(self, mock_streams, mock_session):
        mock_session.list_tools = AsyncMock(
            return_value=SimpleNamespace(tools=[])
        )

        with patch("mcp_client.mcp_client.streamable_http_client", return_value=mock_streams), \
             patch("mcp_client.mcp_client.ClientSession", return_value=mock_session):
            async with MCPClient("http://localhost:3001/mcp") as client:
                tools = await client.list_tools()

        assert tools == []
