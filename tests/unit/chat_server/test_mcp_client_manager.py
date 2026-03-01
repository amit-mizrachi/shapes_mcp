"""Tests for chat-server/src/mcp_client/mcp_client_manager.py — init, tool cache, semaphore."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from mcp_client.mcp_client_manager import MCPClientManager


CONFIG_VALUES = {
    "chat_server.mcp_server_url": "http://localhost:3001/mcp",
    "chat_server.mcp_max_concurrent": 5,
    "chat_server.semaphore_timeout": 30.0,
    "chat_server.mcp_connection.retry_attempts": 3,
    "chat_server.mcp_connection.retry_sleep": 0,
}


def _config_get(key):
    return CONFIG_VALUES[key]


class TestMCPClientManager:
    @pytest.fixture()
    def mock_mcp_client_class(self):
        """Patch MCPClient to return a mock."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.list_tools = AsyncMock(return_value=[
            {"name": "get_schema", "description": "Get schema", "inputSchema": {}},
        ])
        mock_client.call_tool = AsyncMock(return_value="ok")

        with patch("mcp_client.mcp_client_manager.MCPClient", return_value=mock_client) as mock_cls:
            yield mock_cls, mock_client

    @patch("mcp_client.mcp_client_manager.Config")
    async def test_initialize_caches_tools(self, mock_config, mock_mcp_client_class):
        mock_config.get.side_effect = _config_get
        _, mock_client = mock_mcp_client_class
        manager = MCPClientManager()
        await manager.initialize()
        tools = manager.get_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "get_schema"

    @patch("mcp_client.mcp_client_manager.Config")
    async def test_get_tools_before_init_returns_empty(self, mock_config):
        mock_config.get.side_effect = _config_get
        manager = MCPClientManager()
        assert manager.get_tools() == []

    @patch("mcp_client.mcp_client_manager.Config")
    async def test_client_context_manager(self, mock_config, mock_mcp_client_class):
        mock_config.get.side_effect = _config_get
        _, mock_client = mock_mcp_client_class
        manager = MCPClientManager()
        async with manager.client() as client:
            assert client is mock_client

    @patch("mcp_client.mcp_client_manager.Config")
    async def test_semaphore_limits_concurrency(self, mock_config, mock_mcp_client_class):
        """Verify that only max_concurrent clients can be acquired simultaneously."""
        values = {**CONFIG_VALUES, "chat_server.mcp_max_concurrent": 1, "chat_server.semaphore_timeout": 0.1}
        mock_config.get.side_effect = lambda key: values[key]
        _, mock_client = mock_mcp_client_class
        manager = MCPClientManager()

        acquired = asyncio.Event()
        release = asyncio.Event()

        async def hold_client():
            async with manager.client():
                acquired.set()
                await release.wait()

        task = asyncio.create_task(hold_client())
        await acquired.wait()

        with pytest.raises(ConnectionError, match="busy"):
            async with manager.client():
                pass

        release.set()
        await task

    @patch("mcp_client.mcp_client_manager.Config")
    async def test_semaphore_released_on_error(self, mock_config, mock_mcp_client_class):
        """Semaphore should be released even if the client raises."""
        values = {**CONFIG_VALUES, "chat_server.mcp_max_concurrent": 1}
        mock_config.get.side_effect = lambda key: values[key]
        mock_cls, mock_client = mock_mcp_client_class
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))

        manager = MCPClientManager()

        with pytest.raises(Exception, match="Connection failed"):
            async with manager.client():
                pass

        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        async with manager.client() as client:
            assert client is mock_client
