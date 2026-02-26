"""Tests for shared.modules.chat_result.ChatResult."""

from shared.modules.chat_result import ChatResult


class TestChatResult:
    def test_basic_creation(self):
        r = ChatResult(answer="Hello!")
        assert r.answer == "Hello!"
        assert r.tool_calls == []

    def test_with_tool_calls(self):
        calls = [{"tool": "get_schema", "result": "ok"}]
        r = ChatResult(answer="Done", tool_calls=calls)
        assert len(r.tool_calls) == 1

    def test_default_tool_calls(self):
        r = ChatResult(answer="test")
        assert r.tool_calls == []

    def test_mutable(self):
        r = ChatResult(answer="a")
        r.answer = "b"
        assert r.answer == "b"

    def test_tool_calls_default_not_shared(self):
        """Each instance gets its own list."""
        a = ChatResult(answer="a")
        b = ChatResult(answer="b")
        a.tool_calls.append({"x": 1})
        assert b.tool_calls == []
