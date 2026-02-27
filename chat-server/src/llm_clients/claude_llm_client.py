import json
import logging

import anthropic

from llm_clients.llm_client import LLMClient
from shared.config import Config
from shared.modules.llm.llm_response import LLMResponse
from shared.modules.llm.tool_call import ToolCall

logger = logging.getLogger(__name__)


class ClaudeLLMClient(LLMClient):
    def __init__(self):
        self._client = anthropic.AsyncAnthropic()
        self._model = Config.get("chat_server.anthropic_model")
        self._max_tokens = Config.get("chat_server.max_tokens")


    async def invoke(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        """Send messages to the Claude API and return a provider-agnostic LLMResponse."""
        system_prompt, claude_messages = self._convert_messages(messages)
        response = await self._send_request(system_prompt, claude_messages, tools)
        return self._parse_response(response)

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        """Separate the system prompt and translate messages to Claude's format."""
        system_prompt = None
        claude_messages = []

        for message in messages:
            role = message["role"]
            if role == "system":
                system_prompt = message["content"]
            elif role == "user":
                claude_messages.append(message)
            elif role == "assistant" and isinstance(message.get("content"), list):
                assistant_message = self._convert_assistant_tool_message(message)
                claude_messages.append(assistant_message)
            elif role == "assistant":
                claude_messages.append(message)
            elif role == "tool":
                tool_message = self._convert_tool_result_message(message)
                claude_messages.append(tool_message)
            else:
                raise ValueError(f"Unknown role: {role}")

        return system_prompt, claude_messages

    def _convert_tool_result_message(self, message: dict) -> dict:
        """Convert a neutral tool-result message to Claude's user/tool_result format."""
        converted_parts = []
        for tool_result_part in message["content"]:
            claude_tool_result = dict(tool_result_part)
            claude_tool_result["type"] = "tool_result"
            if "tool_call_id" in claude_tool_result:
                claude_tool_result["tool_use_id"] = claude_tool_result.pop("tool_call_id")
            converted_parts.append(claude_tool_result)
        return {"role": "user", "content": converted_parts}

    def _convert_assistant_tool_message(self, message: dict) -> dict:
        """Convert a neutral assistant tool-call message to Claude's tool_use format."""
        converted_parts = []
        for content_block in message["content"]:
            if content_block.get("type") == "tool_call":
                converted_parts.append({
                    "type": "tool_use",
                    "id": content_block["id"],
                    "name": content_block["name"],
                    "input": content_block["arguments"],
                })
            else:
                converted_parts.append(content_block)
        return {"role": "assistant", "content": converted_parts}

    def _convert_tools(self, mcp_tools: list[dict]) -> list[dict]:
        """Convert MCP tool schemas to Claude's tool format."""
        return [
            {
                "name": tool["name"],
                "description": tool.get("description"),
                "input_schema": tool.get("inputSchema"),
            }
            for tool in mcp_tools
        ]

    async def _send_request(self, system_prompt, claude_messages, tools):
        """Build kwargs and call the Claude messages API."""
        kwargs = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": claude_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        try:
            return await self._client.messages.create(**kwargs)
        except anthropic.APIError as err:
            logger.error("Claude API call failed: %s", err)
            raise

    def _parse_response(self, response) -> LLMResponse:
        """Extract text and tool calls from Claude's response blocks."""
        text_segments = []
        tool_calls = []

        for response_block in response.content:
            if response_block.type == "text":
                text_segments.append(response_block.text)
            elif response_block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=response_block.id,
                        name=response_block.name,
                        arguments=(
                            response_block.input
                            if isinstance(response_block.input, dict)
                            else json.loads(response_block.input)
                        ),
                    )
                )

        return LLMResponse(
            text="\n".join(text_segments),
            tool_calls=tool_calls,
        )
