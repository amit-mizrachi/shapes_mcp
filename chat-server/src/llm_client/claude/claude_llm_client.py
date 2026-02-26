from __future__ import annotations

import json
import anthropic
from llm_client.base_llm_client import BaseLLMClient
from shared.config import Config
from shared.modules.llm.llm_response import LLMResponse
from shared.modules.llm.tool_call import ToolCall


class ClaudeLLMClient(BaseLLMClient):
    def __init__(self, model: str):
        self._client = anthropic.AsyncAnthropic()
        self._model = model

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

    async def invoke(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        # Separate system message if present
        system = None
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                api_messages.append(msg)

        kwargs = {
            "model": self._model,
            "max_tokens": Config.get("chat_server.max_tokens"),
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
