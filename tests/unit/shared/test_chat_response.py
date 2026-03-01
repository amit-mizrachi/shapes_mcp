"""Tests for shared.modules.chat_response.ChatResponse."""

from shared.modules.api.chat_response import ChatResponse
from shared.modules.api.tool_call_event import ToolCallEvent, ToolCallEventStatus


class TestChatResponse:
    def test_with_answer_only(self):
        resp = ChatResponse(answer="Hello!")
        assert resp.answer == "Hello!"
        assert resp.tool_calls == []

    def test_with_tool_calls(self):
        event = ToolCallEvent(status=ToolCallEventStatus.SUCCESS, tool="get_schema", arguments={})
        resp = ChatResponse(answer="Done", tool_calls=[event])
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].tool == "get_schema"

    def test_default_tool_calls_is_empty(self):
        resp = ChatResponse(answer="test")
        assert resp.tool_calls == []

    def test_serialization_roundtrip(self):
        event = ToolCallEvent(status=ToolCallEventStatus.SUCCESS, tool="get_schema", arguments={"x": 1})
        resp = ChatResponse(answer="hi", tool_calls=[event])
        data = resp.model_dump()
        restored = ChatResponse(**data)
        assert restored.answer == "hi"
        assert len(restored.tool_calls) == 1
        assert restored.tool_calls[0].tool == "get_schema"
