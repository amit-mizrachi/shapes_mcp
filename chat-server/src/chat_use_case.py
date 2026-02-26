from __future__ import annotations

import logging

from llm_client.base_llm_client import BaseLLMClient
from mcp_client.mcp_client_manager import MCPClientManager
from shared.modules.api.chat_request import ChatRequest
from shared.modules.api.chat_response import ChatResponse

logger = logging.getLogger(__name__)


class ChatUseCase:
    def __init__(
        self,
        llm_client: BaseLLMClient,
        mcp_manager: MCPClientManager,
        system_prompt: str,
        max_iterations: int,
    ):
        self._llm_client = llm_client
        self._mcp_manager = mcp_manager
        self._system_prompt = system_prompt
        self._max_iterations = max_iterations

    async def execute(self, request: ChatRequest) -> ChatResponse:
        messages: list[dict] = [{"role": "system", "content": self._system_prompt}]
        for msg in request.messages:
            messages.append({"role": msg.role, "content": msg.content})

        tools = self._mcp_manager.get_tools()
        trace: list[dict] = []

        for iteration in range(self._max_iterations):
            llm_response = await self._llm_client.invoke(messages, tools)

            if not llm_response.tool_calls:
                return ChatResponse(
                    answer=llm_response.text or "",
                    tool_calls=trace,
                )

            # Build assistant message with tool_use content blocks
            assistant_content: list[dict] = []
            if llm_response.text:
                assistant_content.append({"type": "text", "text": llm_response.text})
            for tc in llm_response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute each tool call and collect results
            tool_results: list[dict] = []
            for tc in llm_response.tool_calls:
                trace.append({"tool": tc.name, "arguments": tc.arguments})
                try:
                    async with self._mcp_manager.client() as mcp_client:
                        result = await mcp_client.call_tool(tc.name, tc.arguments)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result,
                    })
                except Exception:
                    logger.exception("Tool call failed: %s", tc.name)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": f"Error executing {tc.name}: tool call failed",
                        "is_error": True,
                    })

            messages.append({"role": "user", "content": tool_results})

        # Max iterations reached — return what we have
        logger.warning("Max iterations (%d) reached", self._max_iterations)
        return ChatResponse(
            answer="I reached the maximum number of steps. Here is what I found so far.",
            tool_calls=trace,
        )
