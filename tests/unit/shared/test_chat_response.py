"""Tests for shared.modules.chat_response.ChatResponse."""

from shared.modules.api.chat_response import ChatResponse


class TestChatResponse:
    def test_with_answer_only(self):
        resp = ChatResponse(answer="Hello!")
        assert resp.answer == "Hello!"
        assert resp.tool_calls == []

    def test_with_tool_calls(self):
        calls = [{"tool": "get_schema", "result": "ok"}]
        resp = ChatResponse(answer="Done", tool_calls=calls)
        assert len(resp.tool_calls) == 1

    def test_default_tool_calls_is_empty(self):
        resp = ChatResponse(answer="test")
        assert resp.tool_calls == []

    def test_serialization_roundtrip(self):
        resp = ChatResponse(answer="hi", tool_calls=[{"k": "v"}])
        data = resp.model_dump()
        restored = ChatResponse(**data)
        assert restored.answer == "hi"
        assert restored.tool_calls == [{"k": "v"}]
