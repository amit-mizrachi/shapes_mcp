import copy
import logging
from uuid import uuid4

from google import genai
from google.genai import types

from llm_clients.llm_client_interface import LLMClientInterface
from shared.modules.llm.llm_response import LLMResponse
from shared.modules.llm.tool_call import ToolCall

logger = logging.getLogger(__name__)


class GeminiLLMClient(LLMClientInterface):
    def __init__(self, model: str, max_tokens: int):
        self._client = genai.Client()
        self._model = model
        self._max_tokens = max_tokens

    async def invoke(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        """Send messages to Gemini and return a provider-agnostic LLMResponse."""
        system_instruction, contents = self._convert_messages(messages)
        response = await self._send_request(system_instruction, contents, tools)
        return self._parse_response(response)

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list[types.Content]]:
        """Separate the system instruction and translate messages to Gemini's format."""
        system_instruction = None
        contents: list[types.Content] = []

        for message in messages:
            role = message["role"]
            if role == "system":
                system_instruction = message["content"]
            elif role == "user":
                user_message = self._convert_user_message(message)
                contents.append(user_message)
            elif role == "assistant":
                assistant_message = self._convert_assistant_message(message)
                contents.append(assistant_message)
            elif role == "tool":
                tool_message = self._convert_tool_result_message(message)
                contents.append(tool_message)
            else:
                raise ValueError(f"Unknown role: {role}")

        return system_instruction, contents

    def _convert_user_message(self, message: dict) -> types.Content:
        """Convert a user message to Gemini's Content format."""
        return types.Content(
            role="user",
            parts=[types.Part(text=message["content"])],
        )

    def _convert_assistant_message(self, message: dict) -> types.Content:
        """Convert an assistant message (text or tool calls) to Gemini's Content format."""
        parts: list[types.Part] = []
        content = message.get("content", "")

        if isinstance(content, str):
            parts.append(types.Part(text=content))
        else:
            for block in content:
                if block.get("type") == "text":
                    parts.append(types.Part(text=block["text"]))
                elif block.get("type") == "tool_call":
                    parts.append(types.Part(function_call=types.FunctionCall(
                        id=block["id"],
                        name=block["name"],
                        args=block["arguments"],
                    )))

        return types.Content(role="model", parts=parts)

    def _convert_tool_result_message(self, message: dict) -> types.Content:
        """Convert a tool-result message to Gemini's FunctionResponse format."""
        parts = []
        for result in message["content"]:
            parts.append(types.Part(function_response=types.FunctionResponse(
                id=result.get("tool_call_id"),
                name=result.get("name", ""),
                response={"result": result.get("content", "")},
            )))
        return types.Content(role="user", parts=parts)

    def _convert_tools(self, mcp_tools: list[dict]) -> list[types.Tool]:
        """Convert MCP tool schemas to Gemini's tool format."""
        function_declarations = [
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=self._sanitize_schema(tool.get("inputSchema")),
            )
            for tool in mcp_tools
        ]
        return [types.Tool(function_declarations=function_declarations)]

    # ── Schema sanitization ──────────────────────────────────────────────

    @staticmethod
    def _sanitize_schema(schema: dict | None) -> dict | None:
        """Resolve $ref/$defs and strip keys unsupported by Gemini."""
        if not schema:
            return schema
        resolved = GeminiLLMClient._resolve_refs(schema)
        GeminiLLMClient._strip_unsupported_keys(resolved)
        return resolved

    @staticmethod
    def _resolve_refs(schema: dict) -> dict:
        """Deep-copy *schema*, inline all ``$ref`` pointers, then drop ``$defs``."""
        schema = copy.deepcopy(schema)
        defs = schema.pop("$defs", {})
        if not defs:
            return schema

        def _inline(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    ref_path = node["$ref"]  # e.g. "#/$defs/FilterCondition"
                    def_name = ref_path.rsplit("/", 1)[-1]
                    resolved = copy.deepcopy(defs.get(def_name, {}))
                    node.clear()
                    node.update(resolved)
                for value in node.values():
                    _inline(value)
            elif isinstance(node, list):
                for item in node:
                    _inline(item)

        _inline(schema)
        return schema

    @staticmethod
    def _strip_unsupported_keys(node) -> None:
        """Recursively remove ``additionalProperties`` from every nested dict."""
        if isinstance(node, dict):
            node.pop("additionalProperties", None)
            for value in node.values():
                GeminiLLMClient._strip_unsupported_keys(value)
        elif isinstance(node, list):
            for item in node:
                GeminiLLMClient._strip_unsupported_keys(item)

    async def _send_request(self, system_instruction, contents, tools):
        """Build config and call the Gemini content generation API."""
        config = types.GenerateContentConfig(max_output_tokens=self._max_tokens)
        if system_instruction:
            config.system_instruction = system_instruction
        if tools:
            config.tools = self._convert_tools(tools)

        return await self._client.aio.models.generate_content(
            model=self._model, contents=contents, config=config,
        )

    def _parse_response(self, response) -> LLMResponse:
        """Extract text and tool calls from Gemini's response candidates."""
        if not response.candidates:
            raise RuntimeError(
                "Gemini returned no candidates — response may have been blocked. "
                f"Prompt feedback: {response.prompt_feedback}"
            )

        text_segments: list[str] = []
        tool_calls: list[ToolCall] = []

        for part in response.candidates[0].content.parts:
            if part.text:
                text_segments.append(part.text)
            elif part.function_call:
                function_call = part.function_call
                tool_call_id = function_call.id or f"gemini_{uuid4().hex[:12]}"
                tool_calls.append(ToolCall(
                    id=tool_call_id,
                    name=function_call.name,
                    arguments=dict(function_call.args) if function_call.args else {},
                ))

        return LLMResponse(text="\n".join(text_segments), tool_calls=tool_calls)
