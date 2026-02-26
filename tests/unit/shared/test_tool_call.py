"""Tests for shared.modules.tool_call.ToolCall."""

from shared.modules.llm.tool_call import ToolCall


class TestToolCall:
    def test_basic_creation(self):
        tc = ToolCall(id="tc_1", name="get_schema", arguments={})
        assert tc.id == "tc_1"
        assert tc.name == "get_schema"
        assert tc.arguments == {}

    def test_with_arguments(self):
        tc = ToolCall(id="tc_2", name="select_rows", arguments={"limit": 10})
        assert tc.arguments["limit"] == 10

    def test_mutable(self):
        tc = ToolCall(id="tc_1", name="test", arguments={})
        tc.name = "changed"
        assert tc.name == "changed"

    def test_equality(self):
        a = ToolCall(id="1", name="x", arguments={"a": 1})
        b = ToolCall(id="1", name="x", arguments={"a": 1})
        assert a == b
