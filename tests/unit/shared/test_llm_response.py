"""Tests for shared.modules.llm_response.LLMResponse."""

from shared.modules.llm.llm_response import LLMResponse
from shared.modules.llm.tool_call import ToolCall


class TestLLMResponse:
    def test_default_values(self):
        r = LLMResponse()
        assert r.text is None
        assert r.tool_calls == []

    def test_with_text(self):
        r = LLMResponse(text="Hello!")
        assert r.text == "Hello!"

    def test_with_tool_calls(self):
        tc = ToolCall(id="1", name="test", arguments={})
        r = LLMResponse(text="hi", tool_calls=[tc])
        assert len(r.tool_calls) == 1
        assert r.tool_calls[0].name == "test"

    def test_tool_calls_default_not_shared(self):
        a = LLMResponse()
        b = LLMResponse()
        a.tool_calls.append(ToolCall(id="1", name="x", arguments={}))
        assert b.tool_calls == []

    def test_mutable(self):
        r = LLMResponse(text="a")
        r.text = "b"
        assert r.text == "b"
