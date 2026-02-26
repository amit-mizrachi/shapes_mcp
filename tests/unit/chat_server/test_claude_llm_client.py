"""Tests for chat-server/src/llm_client/claude_llm_client.py — tool conversion, response parsing."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_client.claude.claude_llm_client import ClaudeLLMClient


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(id: str, name: str, input: dict):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


class TestConvertTools:
    def test_converts_mcp_to_claude_format(self):
        client = ClaudeLLMClient(model="test-model", max_tokens=4096)
        mcp_tools = [
            {
                "name": "get_schema",
                "description": "Get schema",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]
        result = client._convert_tools(mcp_tools)
        assert len(result) == 1
        assert result[0]["name"] == "get_schema"
        assert result[0]["description"] == "Get schema"
        assert result[0]["input_schema"] == {"type": "object", "properties": {}}

    def test_missing_description(self):
        client = ClaudeLLMClient(model="test-model", max_tokens=4096)
        mcp_tools = [{"name": "tool1", "inputSchema": {}}]
        result = client._convert_tools(mcp_tools)
        assert result[0]["description"] is None

    def test_empty_tools(self):
        client = ClaudeLLMClient(model="test-model", max_tokens=4096)
        assert client._convert_tools([]) == []


class TestInvoke:
    @pytest.fixture()
    def mock_anthropic(self):
        with patch("llm_client.claude.claude_llm_client.anthropic") as mock_mod:
            mock_client = AsyncMock()
            mock_mod.AsyncAnthropic.return_value = mock_client
            yield mock_client

    async def test_text_only_response(self, mock_anthropic):
        mock_anthropic.messages.create = AsyncMock(return_value=SimpleNamespace(
            content=[_text_block("Hello world")],
        ))
        client = ClaudeLLMClient(model="test-model", max_tokens=4096)
        result = await client.invoke(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )
        assert result.text == "Hello world"
        assert result.tool_calls == []

    async def test_tool_call_response(self, mock_anthropic):
        mock_anthropic.messages.create = AsyncMock(return_value=SimpleNamespace(
            content=[
                _text_block("Let me check"),
                _tool_use_block("tc_1", "get_schema", {}),
            ],
        ))
        client = ClaudeLLMClient(model="test-model", max_tokens=4096)
        result = await client.invoke(
            messages=[{"role": "user", "content": "show schema"}],
            tools=[{"name": "get_schema", "description": "x", "inputSchema": {}}],
        )
        assert result.text == "Let me check"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_schema"
        assert result.tool_calls[0].id == "tc_1"

    async def test_multiple_tool_calls(self, mock_anthropic):
        mock_anthropic.messages.create = AsyncMock(return_value=SimpleNamespace(
            content=[
                _tool_use_block("tc_1", "get_schema", {}),
                _tool_use_block("tc_2", "select_rows", {"limit": 5}),
            ],
        ))
        client = ClaudeLLMClient(model="test-model", max_tokens=4096)
        result = await client.invoke(
            messages=[{"role": "user", "content": "analyze"}],
            tools=[],
        )
        assert len(result.tool_calls) == 2
        assert result.tool_calls[1].arguments == {"limit": 5}

    async def test_system_message_separated(self, mock_anthropic):
        mock_anthropic.messages.create = AsyncMock(return_value=SimpleNamespace(
            content=[_text_block("ok")],
        ))
        client = ClaudeLLMClient(model="test-model", max_tokens=4096)
        await client.invoke(
            messages=[
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "hi"},
            ],
            tools=[],
        )
        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "You are helpful"
        # System message should NOT be in messages list
        for msg in call_kwargs["messages"]:
            assert msg["role"] != "system"

    async def test_no_system_message(self, mock_anthropic):
        mock_anthropic.messages.create = AsyncMock(return_value=SimpleNamespace(
            content=[_text_block("ok")],
        ))
        client = ClaudeLLMClient(model="test-model", max_tokens=4096)
        await client.invoke(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )
        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert "system" not in call_kwargs

    async def test_tool_input_as_string(self, mock_anthropic):
        """Handle case where tool input is returned as JSON string."""
        mock_anthropic.messages.create = AsyncMock(return_value=SimpleNamespace(
            content=[_tool_use_block("tc_1", "select_rows", '{"limit": 5}')],
        ))
        client = ClaudeLLMClient(model="test-model", max_tokens=4096)
        result = await client.invoke(
            messages=[{"role": "user", "content": "query"}],
            tools=[],
        )
        assert result.tool_calls[0].arguments == {"limit": 5}

    async def test_concatenates_multiple_text_blocks(self, mock_anthropic):
        mock_anthropic.messages.create = AsyncMock(return_value=SimpleNamespace(
            content=[_text_block("Hello"), _text_block("World")],
        ))
        client = ClaudeLLMClient(model="test-model", max_tokens=4096)
        result = await client.invoke(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )
        assert result.text == "Hello\nWorld"
