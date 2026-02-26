"""Tests for shared.modules.tool_call_trace.ToolCallTrace."""

from shared.modules.tool_call_trace import ToolCallTrace


class TestToolCallTrace:
    def test_basic_creation(self):
        t = ToolCallTrace(name="get_schema", arguments={}, result='{"table": "data"}')
        assert t.name == "get_schema"
        assert t.result == '{"table": "data"}'

    def test_with_arguments(self):
        t = ToolCallTrace(name="select_rows", arguments={"limit": 5}, result="ok")
        assert t.arguments["limit"] == 5

    def test_mutable(self):
        t = ToolCallTrace(name="x", arguments={}, result="r")
        t.result = "updated"
        assert t.result == "updated"
