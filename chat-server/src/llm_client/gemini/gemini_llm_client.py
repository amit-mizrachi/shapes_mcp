from __future__ import annotations

import logging
from uuid import uuid4

from google import genai
from google.genai import types

from llm_client.base_llm_client import BaseLLMClient
from shared.modules.llm.llm_response import LLMResponse
from shared.modules.llm.tool_call import ToolCall

logger = logging.getLogger(__name__)


class GeminiLLMClient(BaseLLMClient):
    def __init__(self, model: str, max_tokens: int):
        self._client = genai.Client()
        self._model = model
        self._max_tokens = max_tokens

    @staticmethod
    def _convert_tools(mcp_tools: list[dict]) -> list[types.Tool]:
        declarations = []
        for tool in mcp_tools:
            declarations.append(types.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=tool.get("inputSchema"),
            ))
        return [types.Tool(function_declarations=declarations)]

    @staticmethod
    def _convert_messages(
        messages: list[dict],
    ) -> tuple[str | None, list[types.Content]]:
        system_instruction = None
        contents: list[types.Content] = []

        for msg in messages:
            role = msg["role"]

            if role == "system":
                system_instruction = msg["content"]

            elif role == "user":
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(text=msg["content"])],
                ))

            elif role == "assistant":
                parts: list[types.Part] = []
                content = msg.get("content", "")
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
                contents.append(types.Content(role="model", parts=parts))

            elif role == "tool":
                parts = []
                for result in msg["content"]:
                    parts.append(types.Part(function_response=types.FunctionResponse(
                        id=result.get("tool_call_id"),
                        name=result.get("name", ""),
                        response={"result": result.get("content", "")},
                    )))
                contents.append(types.Content(role="user", parts=parts))

        return system_instruction, contents

    async def invoke(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        system_instruction, contents = self._convert_messages(messages)

        config = types.GenerateContentConfig(
            max_output_tokens=self._max_tokens,
        )
        if system_instruction:
            config.system_instruction = system_instruction
        if tools:
            config.tools = self._convert_tools(tools)

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )

        if not response.candidates:
            raise RuntimeError(
                "Gemini returned no candidates — response may have been blocked. "
                f"Prompt feedback: {response.prompt_feedback}"
            )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for part in response.candidates[0].content.parts:
            if part.text:
                text_parts.append(part.text)
            elif part.function_call:
                fc = part.function_call
                call_id = fc.id if fc.id else f"gemini_{uuid4().hex[:12]}"
                tool_calls.append(ToolCall(
                    id=call_id,
                    name=fc.name,
                    arguments=dict(fc.args) if fc.args else {},
                ))

        return LLMResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
        )
