"""Tests for chat-server/src/chat_orchestrator.py — agent loop, max iterations, tracing."""

from unittest.mock import AsyncMock

import pytest

from shared.config import Config
from shared.modules.api.chat_request import ChatRequest
from shared.modules.api.message_item import MessageItem
from shared.modules.llm.llm_response import LLMResponse
from shared.modules.llm.tool_call import ToolCall
from chat_orchestrator import ChatOrchestrator


def _request(content: str = "hello") -> ChatRequest:
    return ChatRequest(messages=[MessageItem(role="user", content=content)])


def _text_response(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[])


def _tool_response(tool_name: str = "get_schema", tool_args: dict = None, text: str = None) -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=[ToolCall(id="tc_1", name=tool_name, arguments=tool_args or {})],
    )


def _make_orchestrator(llm_client, mcp_manager) -> ChatOrchestrator:
    return ChatOrchestrator(
        llm_client=llm_client,
        mcp_manager=mcp_manager,
    )


class TestExecute:
    async def test_simple_text_response(self, mock_llm_client, mock_mcp_manager):
        orch =_make_orchestrator(mock_llm_client, mock_mcp_manager)
        result = await orch.execute(_request())
        assert result.answer == "Hello!"
        assert result.tool_calls == []

    async def test_exception_propagates(self, mock_llm_client, mock_mcp_manager):
        mock_llm_client.invoke = AsyncMock(side_effect=RuntimeError("LLM crashed"))
        orch =_make_orchestrator(mock_llm_client, mock_mcp_manager)
        with pytest.raises(RuntimeError, match="LLM crashed"):
            await orch.execute(_request())


class TestAgentLoop:
    async def test_single_tool_call_then_response(self, mock_llm_client, mock_mcp_manager, mock_mcp_client):
        """LLM calls a tool, gets result, then returns text."""
        mock_llm_client.invoke = AsyncMock(side_effect=[
            _tool_response("get_schema"),
            _text_response("The schema has 2 columns."),
        ])

        orch =_make_orchestrator(mock_llm_client, mock_mcp_manager)
        result = await orch.execute(_request("show schema"))

        assert result.answer == "The schema has 2 columns."
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool == "get_schema"
        mock_mcp_client.call_tool.assert_called_once_with("get_schema", {})

    async def test_multiple_tool_calls_in_sequence(self, mock_llm_client, mock_mcp_manager, mock_mcp_client):
        """LLM calls tool, gets result, calls another tool, then responds."""
        mock_llm_client.invoke = AsyncMock(side_effect=[
            _tool_response("get_schema"),
            _tool_response("select_rows", {"limit": 5}),
            _text_response("Found 5 rows."),
        ])

        orch =_make_orchestrator(mock_llm_client, mock_mcp_manager)
        result = await orch.execute(_request("analyze data"))

        assert result.answer == "Found 5 rows."
        assert len(result.tool_calls) == 2

    async def test_max_iterations_reached(self, mock_llm_client, mock_mcp_manager, mock_mcp_client):
        """If LLM keeps calling tools beyond max_iterations, return fallback."""
        mock_llm_client.invoke = AsyncMock(return_value=_tool_response("get_schema"))
        max_iterations = Config.get("chat_server.max_iterations")

        orch =_make_orchestrator(mock_llm_client, mock_mcp_manager)
        result = await orch.execute(_request("loop"))

        assert "maximum number of steps" in result.answer.lower()
        assert len(result.tool_calls) == max_iterations

    async def test_tool_call_failure_handled(self, mock_llm_client, mock_mcp_manager, mock_mcp_client):
        """If a tool call raises, the error is captured and sent back to LLM."""
        mock_llm_client.invoke = AsyncMock(side_effect=[
            _tool_response("get_schema"),
            _text_response("Sorry, something went wrong."),
        ])
        mock_mcp_client.call_tool = AsyncMock(side_effect=Exception("Tool failed"))

        orch =_make_orchestrator(mock_llm_client, mock_mcp_manager)
        result = await orch.execute(_request("query"))

        assert result.answer == "Sorry, something went wrong."

    async def test_no_text_in_response(self, mock_llm_client, mock_mcp_manager):
        """If LLM returns None text with no tool calls, return empty answer."""
        mock_llm_client.invoke = AsyncMock(return_value=LLMResponse(text=None, tool_calls=[]))
        orch =_make_orchestrator(mock_llm_client, mock_mcp_manager)
        result = await orch.execute(_request())
        assert result.answer == ""

    async def test_trace_records_tool_calls(self, mock_llm_client, mock_mcp_manager, mock_mcp_client):
        mock_mcp_client.call_tool = AsyncMock(return_value='{"table": "people"}')
        mock_llm_client.invoke = AsyncMock(side_effect=[
            _tool_response("get_schema"),
            _text_response("Done"),
        ])

        orch =_make_orchestrator(mock_llm_client, mock_mcp_manager)
        result = await orch.execute(_request("schema"))

        assert result.tool_calls[0].tool == "get_schema"
        assert result.tool_calls[0].arguments == {}

    async def test_system_prompt_prepended(self, mock_llm_client, mock_mcp_manager):
        orch =_make_orchestrator(mock_llm_client, mock_mcp_manager)
        await orch.execute(_request())

        call_args = mock_llm_client.invoke.call_args
        messages = call_args[0][0]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == Config.get("chat_server.system_prompt")

    async def test_tool_call_with_text(self, mock_llm_client, mock_mcp_manager, mock_mcp_client):
        """LLM returns both text and tool call in same response."""
        mock_llm_client.invoke = AsyncMock(side_effect=[
            _tool_response("get_schema", text="Let me check the schema"),
            _text_response("Schema has 3 columns"),
        ])

        orch =_make_orchestrator(mock_llm_client, mock_mcp_manager)
        result = await orch.execute(_request("schema"))
        assert result.answer == "Schema has 3 columns"
