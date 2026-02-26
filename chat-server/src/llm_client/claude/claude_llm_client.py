from __future__ import annotations

import json
import anthropic
from llm_client.base_llm_client import BaseLLMClient
from shared.modules.llm.llm_response import LLMResponse
from shared.modules.llm.tool_call import ToolCall


class ClaudeLLMClient(BaseLLMClient):
    def __init__(self, model: str, max_tokens: int):
        self._client = anthropic.AsyncAnthropic()
        self._model = model
        self._max_tokens = max_tokens

    def _convert_tools(self, mcp_tools: list[dict]) -> list[dict]:
        """Convert MCP tool schemas to Claude's tool format."""
        claude_tools = []
        for tool in mcp_tools:
            claude_tools.append({
                "name": tool["name"],
                "description": tool.get("description"),
                "input_schema": tool.get("inputSchema")
            })
        return claude_tools

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        """Translate provider-agnostic messages to Claude's format."""
        system = None
        api_messages = []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                system = msg["content"]
            elif role == "tool":
                # Tool results: neutral role "tool" → Claude role "user"
                converted_parts = []
                for part in msg["content"]:
                    converted = dict(part)
                    converted["type"] = "tool_result"
                    if "tool_call_id" in converted:
                        converted["tool_use_id"] = converted.pop("tool_call_id")
                    converted_parts.append(converted)
                api_messages.append({"role": "user", "content": converted_parts})
            elif role == "assistant" and isinstance(msg.get("content"), list):
                # Assistant message with tool calls: neutral → Claude
                converted_parts = []
                for part in msg["content"]:
                    if part.get("type") == "tool_call":
                        converted_parts.append({
                            "type": "tool_use",
                            "id": part["id"],
                            "name": part["name"],
                            "input": part["arguments"],
                        })
                    else:
                        converted_parts.append(part)
                api_messages.append({"role": "assistant", "content": converted_parts})
            else:
                api_messages.append(msg)
        return system, api_messages

    async def invoke(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        system, api_messages = self._convert_messages(messages)

        kwargs = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": api_messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = await self._client.messages.create(**kwargs)

        text_parts = []
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else json.loads(block.input),
                    )
                )

        return LLMResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
        )
