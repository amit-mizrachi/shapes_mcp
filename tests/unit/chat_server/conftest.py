"""Chat server test fixtures: mock LLM, mock MCP manager, orchestrator."""

from contextlib import asynccontextmanager
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.modules.llm.llm_response import LLMResponse
from shared.modules.llm.tool_call import ToolCall


@pytest.fixture()
def mock_llm_client():
    """Mock LLM client returning a simple text response (no tool calls)."""
    client = AsyncMock()
    client.invoke = AsyncMock(return_value=LLMResponse(text="Hello!", tool_calls=[]))
    return client


@pytest.fixture()
def mock_mcp_client():
    """Mock MCP client with list_tools and call_tool."""
    client = AsyncMock()
    client.list_tools = AsyncMock(return_value=[
        {"name": "get_schema", "description": "Get schema", "inputSchema": {}},
    ])
    client.call_tool = AsyncMock(return_value='{"table": "test"}')
    return client


@pytest.fixture()
def mock_mcp_manager(mock_mcp_client):
    """Mock MCPClientManager that yields a mock MCP client."""
    manager = MagicMock()
    manager.get_tools = MagicMock(return_value=[
        {"name": "get_schema", "description": "Get schema", "inputSchema": {}},
    ])

    @asynccontextmanager
    async def _client():
        yield mock_mcp_client

    manager.client = _client
    return manager


def make_llm_response_with_tool_call(
    text: Optional[str] = None,
    tool_name: str = "get_schema",
    tool_args: Optional[dict] = None,
    tool_id: str = "tc_1",
) -> LLMResponse:
    """Helper to create an LLMResponse with a single tool call."""
    return LLMResponse(
        text=text,
        tool_calls=[ToolCall(id=tool_id, name=tool_name, arguments=tool_args or {})],
    )
