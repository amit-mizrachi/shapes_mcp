"""Tests for chat-server/src/llm_clients/gemini/gemini_llm_client.py — tool conversion, message conversion, invoke."""

from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_clients.gemini_llm_client import GeminiLLMClient
from shared.modules.llm.tool_call import ToolCall
from shared.modules.llm.messages import (
    AssistantMessage,
    SystemMessage,
    ToolMessage,
    ToolResult,
    UserMessage,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_response(parts, finish_reason="STOP"):
    """Build a minimal GenerateContentResponse-like object."""
    candidate = SimpleNamespace(
        content=SimpleNamespace(parts=parts),
        finish_reason=finish_reason,
    )
    return SimpleNamespace(candidates=[candidate], prompt_feedback=None)


def _text_part(text: str):
    return SimpleNamespace(text=text, function_call=None)


def _fc_part(name: str, args: dict, id: Optional[str] = None):
    return SimpleNamespace(
        text=None,
        function_call=SimpleNamespace(id=id, name=name, args=args),
    )


# ── TestConvertTools ─────────────────────────────────────────────────────────

class TestConvertTools:
    @pytest.fixture()
    def client(self):
        with patch("llm_clients.gemini_llm_client.genai"):
            return GeminiLLMClient()

    def test_converts_mcp_to_gemini_format(self, client):
        mcp_tools = [
            {
                "name": "get_schema",
                "description": "Get schema",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]
        result = client._convert_tools(mcp_tools)
        assert len(result) == 1
        decls = result[0].function_declarations
        assert len(decls) == 1
        assert decls[0].name == "get_schema"
        assert decls[0].description == "Get schema"

    def test_multiple_tools(self, client):
        mcp_tools = [
            {"name": "tool_a", "description": "A", "inputSchema": {}},
            {"name": "tool_b", "description": "B", "inputSchema": {}},
        ]
        result = client._convert_tools(mcp_tools)
        assert len(result[0].function_declarations) == 2

    def test_empty_tools(self, client):
        result = client._convert_tools([])
        assert result[0].function_declarations == []


# ── TestConvertMessages ──────────────────────────────────────────────────────

class TestConvertMessages:
    @pytest.fixture()
    def client(self):
        with patch("llm_clients.gemini_llm_client.genai"):
            return GeminiLLMClient()

    def test_system_message_extracted(self, client):
        system, contents = client._convert_messages([
            SystemMessage(content="Be helpful"),
            UserMessage(content="hi"),
        ])
        assert system == "Be helpful"
        assert len(contents) == 1
        assert contents[0].role == "user"

    def test_user_message(self, client):
        _, contents = client._convert_messages([
            UserMessage(content="hello"),
        ])
        assert len(contents) == 1
        assert contents[0].role == "user"
        assert contents[0].parts[0].text == "hello"

    def test_assistant_text_message(self, client):
        _, contents = client._convert_messages([
            AssistantMessage(text="I can help"),
        ])
        assert len(contents) == 1
        assert contents[0].role == "model"
        assert contents[0].parts[0].text == "I can help"

    def test_assistant_tool_call_message(self, client):
        _, contents = client._convert_messages([
            AssistantMessage(
                text="Let me check",
                tool_calls=[ToolCall(id="tc_1", name="get_schema", arguments={"x": 1})],
            ),
        ])
        assert len(contents) == 1
        assert contents[0].role == "model"
        parts = contents[0].parts
        assert parts[0].text == "Let me check"
        fc = parts[1].function_call
        assert fc.name == "get_schema"
        assert fc.args == {"x": 1}
        assert fc.id == "tc_1"

    def test_tool_result_message(self, client):
        _, contents = client._convert_messages([
            ToolMessage(results=[
                ToolResult(tool_call_id="tc_1", name="get_schema", content="ok"),
            ]),
        ])
        assert len(contents) == 1
        assert contents[0].role == "user"
        fr = contents[0].parts[0].function_response
        assert fr.name == "get_schema"
        assert fr.id == "tc_1"
        assert fr.response == {"result": "ok"}

    def test_no_system_returns_none(self, client):
        system, _ = client._convert_messages([
            UserMessage(content="hi"),
        ])
        assert system is None


# ── TestInvoke ───────────────────────────────────────────────────────────────

class TestInvoke:
    @pytest.fixture()
    def mock_genai(self):
        with patch("llm_clients.gemini_llm_client.genai") as mock_mod:
            mock_client = MagicMock()
            mock_mod.Client.return_value = mock_client
            mock_client.aio.models.generate_content = AsyncMock()
            yield mock_client

    async def test_text_only_response(self, mock_genai):
        mock_genai.aio.models.generate_content.return_value = _make_response([
            _text_part("Hello world"),
        ])
        client = GeminiLLMClient()
        result = await client.invoke(
            messages=[UserMessage(content="hi")],
            tools=[],
        )
        assert result.text == "Hello world"
        assert result.tool_calls == []

    async def test_function_call_response(self, mock_genai):
        mock_genai.aio.models.generate_content.return_value = _make_response([
            _text_part("Let me check"),
            _fc_part("get_schema", {}, id="gc_1"),
        ])
        client = GeminiLLMClient()
        result = await client.invoke(
            messages=[UserMessage(content="show schema")],
            tools=[{"name": "get_schema", "description": "x", "inputSchema": {}}],
        )
        assert result.text == "Let me check"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_schema"
        assert result.tool_calls[0].id == "gc_1"

    async def test_function_call_id_fallback(self, mock_genai):
        mock_genai.aio.models.generate_content.return_value = _make_response([
            _fc_part("get_schema", {}, id=None),
        ])
        client = GeminiLLMClient()
        result = await client.invoke(
            messages=[UserMessage(content="schema")],
            tools=[],
        )
        assert result.tool_calls[0].id.startswith("gemini_")
        assert len(result.tool_calls[0].id) == len("gemini_") + 12

    async def test_system_instruction_passed(self, mock_genai):
        mock_genai.aio.models.generate_content.return_value = _make_response([
            _text_part("ok"),
        ])
        client = GeminiLLMClient()
        await client.invoke(
            messages=[
                SystemMessage(content="You are helpful"),
                UserMessage(content="hi"),
            ],
            tools=[],
        )
        call_kwargs = mock_genai.aio.models.generate_content.call_args.kwargs
        assert call_kwargs["config"].system_instruction == "You are helpful"

    async def test_empty_candidates_raises(self, mock_genai):
        mock_genai.aio.models.generate_content.return_value = SimpleNamespace(
            candidates=[], prompt_feedback="BLOCKED",
        )
        client = GeminiLLMClient()
        with pytest.raises(RuntimeError, match="no usable content"):
            await client.invoke(
                messages=[UserMessage(content="hi")],
                tools=[],
            )

    async def test_multiple_text_parts_concatenated(self, mock_genai):
        mock_genai.aio.models.generate_content.return_value = _make_response([
            _text_part("Hello"),
            _text_part("World"),
        ])
        client = GeminiLLMClient()
        result = await client.invoke(
            messages=[UserMessage(content="hi")],
            tools=[],
        )
        assert result.text == "Hello\nWorld"


# ── TestSanitizeSchema ───────────────────────────────────────────────────

class TestSanitizeSchema:
    @pytest.fixture()
    def client(self):
        with patch("llm_clients.gemini_llm_client.genai"):
            return GeminiLLMClient()

    def test_strips_additional_properties_from_nested(self, client):
        schema = {
            "type": "object",
            "properties": {
                "filters": {
                    "anyOf": [
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"column": {"type": "string"}},
                                "additionalProperties": False,
                            },
                        },
                        {"type": "null"},
                    ],
                }
            },
            "additionalProperties": False,
        }
        result = client._sanitize_schema(schema)
        assert "additionalProperties" not in result
        items = result["properties"]["filters"]["anyOf"][0]["items"]
        assert "additionalProperties" not in items

    def test_resolves_refs_and_defs(self, client):
        schema = {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/FilterCondition"},
                }
            },
            "$defs": {
                "FilterCondition": {
                    "type": "object",
                    "properties": {
                        "column": {"type": "string"},
                        "op": {"type": "string"},
                    },
                }
            },
        }
        result = client._sanitize_schema(schema)
        assert "$defs" not in result
        items = result["properties"]["filters"]["items"]
        assert "$ref" not in items
        assert items["type"] == "object"
        assert "column" in items["properties"]

    def test_clean_schema_passes_through(self, client):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        result = client._sanitize_schema(schema)
        assert result == schema

    def test_none_schema_returns_none(self, client):
        assert client._sanitize_schema(None) is None

    def test_empty_schema_returns_empty(self, client):
        assert client._sanitize_schema({}) == {}

    def test_convert_tools_with_problematic_schema(self, client):
        """Integration: _convert_tools doesn't raise with $ref/$defs/additionalProperties."""
        mcp_tools = [
            {
                "name": "select_rows",
                "description": "Select rows",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filters": {
                            "anyOf": [
                                {
                                    "type": "array",
                                    "items": {"$ref": "#/$defs/FilterCondition"},
                                },
                                {"type": "null"},
                            ],
                        }
                    },
                    "$defs": {
                        "FilterCondition": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "op": {"type": "string"},
                            },
                            "additionalProperties": False,
                        }
                    },
                    "additionalProperties": False,
                },
            }
        ]
        result = client._convert_tools(mcp_tools)
        decl = result[0].function_declarations[0]
        assert decl.name == "select_rows"
        params = decl.parameters
        assert "$defs" not in params
        assert "additionalProperties" not in params
