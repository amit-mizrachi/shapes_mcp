import json
import logging
from typing import Optional

import anthropic

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


class ClaudeLLMClient(LLMClient):
    def __init__(self):
        self._client = anthropic.AsyncAnthropic()
        self._model = Config.get("chat_server.anthropic_model")
        self._max_tokens = Config.get("chat_server.max_tokens")


    async def invoke(self, messages: list[ChatMessage], tools: list[dict]) -> LLMResponse:
        """Send messages to the Claude API and return a provider-agnostic LLMResponse."""
        system_prompt, claude_messages = self._convert_messages(messages)
        response = await self._send_request(system_prompt, claude_messages, tools)
        return self._parse_response(response)

    def _convert_messages(self, messages: list[ChatMessage]) -> tuple[Optional[str], list[dict]]:
        """Separate the system prompt and translate messages to Claude's format."""
        system_prompt = None
        claude_messages = []

        for message in messages:
            match message:
                case SystemMessage():
                    system_prompt = message.content
                case UserMessage():
                    claude_messages.append({"role": "user", "content": message.content})
                case AssistantMessage():
                    claude_messages.append(self._convert_assistant_message(message))
                case ToolMessage():
                    claude_messages.append(self._convert_tool_message(message))

        return system_prompt, claude_messages

    def _convert_assistant_message(self, msg: AssistantMessage) -> dict:
        """Convert an AssistantMessage to Claude's tool_use format."""
        content: list[dict] = []
        if msg.text:
            content.append({"type": "text", "text": msg.text})
        for tc in msg.tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.arguments,
            })
        return {"role": "assistant", "content": content}

    def _convert_tool_message(self, msg: ToolMessage) -> dict:
        """Convert a ToolMessage to Claude's user/tool_result format."""
        content = []
        for result in msg.results:
            part: dict = {
                "type": "tool_result",
                "tool_use_id": result.tool_call_id,
                "name": result.name,
                "content": result.content,
            }
            if result.is_error:
                part["is_error"] = True
            content.append(part)
        return {"role": "user", "content": content}

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
        except anthropic.APIError as error:
            logger.error("Claude API call failed: %s", error)
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
