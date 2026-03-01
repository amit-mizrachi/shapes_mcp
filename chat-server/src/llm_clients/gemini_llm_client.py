import copy
import logging
from typing import Optional
from uuid import uuid4

from google import genai
from google.genai import types

from llm_clients.llm_client import LLMClient
from shared.config import Config
from shared.modules.llm.llm_response import LLMResponse
from shared.modules.llm.tool_call import ToolCall
from shared.modules.llm.messages import (
    AssistantMessage,
    ChatMessage,
    SystemMessage,
    ToolMessage,
    UserMessage,
)

logger = logging.getLogger(__name__)


class GeminiLLMClient(LLMClient):
    def __init__(self):
        self._client = genai.Client()
        self._model = Config.get("chat_server.gemini_model")
        self._max_tokens = Config.get("chat_server.gemini_max_tokens")

    async def invoke(self, messages: list[ChatMessage], tools: list[dict]) -> LLMResponse:
        """Send messages to Gemini and return a provider-agnostic LLMResponse."""
        system_instruction, contents = self._convert_messages(messages)
        response = await self._send_request(system_instruction, contents, tools)
        return self._parse_response(response)

    def _convert_messages(self, messages: list[ChatMessage]) -> tuple[Optional[str], list[types.Content]]:
        """Separate the system instruction and translate messages to Gemini's format."""
        system_instruction = None
        contents: list[types.Content] = []

        for message in messages:
            match message:
                case SystemMessage():
                    system_instruction = message.content
                case UserMessage():
                    contents.append(self._convert_user_message(message))
                case AssistantMessage():
                    contents.append(self._convert_assistant_message(message))
                case ToolMessage():
                    contents.append(self._convert_tool_message(message))

        return system_instruction, contents

    def _convert_user_message(self, msg: UserMessage) -> types.Content:
        """Convert a UserMessage to Gemini's Content format."""
        return types.Content(
            role="user",
            parts=[types.Part(text=msg.content)],
        )

    def _convert_assistant_message(self, msg: AssistantMessage) -> types.Content:
        """Convert an AssistantMessage to Gemini's Content format."""
        parts: list[types.Part] = []
        if msg.text:
            parts.append(types.Part(text=msg.text))
        for tc in msg.tool_calls:
            parts.append(types.Part(function_call=types.FunctionCall(
                id=tc.id,
                name=tc.name,
                args=tc.arguments,
            )))
        return types.Content(role="model", parts=parts)

    def _convert_tool_message(self, msg: ToolMessage) -> types.Content:
        """Convert a ToolMessage to Gemini's FunctionResponse format."""
        parts = []
        for result in msg.results:
            parts.append(types.Part(function_response=types.FunctionResponse(
                id=result.tool_call_id,
                name=result.name,
                response={"result": result.content},
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
    def _sanitize_schema(schema: Optional[dict]) -> Optional[dict]:
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
        definitions = schema.pop("$defs", {})
        if not definitions:
            return schema

        def _inline(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    reference_path = node["$ref"]  # e.g. "#/$defs/FilterCondition"
                    definition_name = reference_path.rsplit("/", 1)[-1]
                    resolved = copy.deepcopy(definitions.get(definition_name, {}))
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
        candidate = response.candidates[0] if response.candidates else None
        if not candidate or not candidate.content or not candidate.content.parts:
            finish_reason = getattr(candidate, 'finish_reason', None)
            if finish_reason and "MALFORMED_FUNCTION_CALL" in str(finish_reason):
                finish_message = getattr(candidate, "finish_message", None)
                logger.warning("Gemini produced a malformed function call (finish_reason=%s, message=%s)",
                    finish_reason,
                    finish_message,
                )
                return LLMResponse(
                    malformed_function_call=True,
                    malformed_message=finish_message,
                )
            raise RuntimeError(
                "Gemini returned no usable content — response may have been blocked. "
                f"Finish reason: {finish_reason}, "
                f"Prompt feedback: {response.prompt_feedback}"
            )

        text_segments: list[str] = []
        tool_calls: list[ToolCall] = []

        for part in candidate.content.parts:
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
