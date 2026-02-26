import asyncio
import json
import logging

from shared.config import Config
from shared.modules.api.chat_response import ChatResponse
from llm_client.base_llm_client import BaseLLMClient
from mcp_client.mcp_client import MCPClient
from mcp_client.mcp_client_manager import MCPClientManager

logger = logging.getLogger(__name__)


class ChatOrchestrator:
    def __init__(self, llm_client: BaseLLMClient, mcp: MCPClientManager):
        self._llm = llm_client
        self._mcp = mcp

    async def chat(self, messages: list[dict]) -> ChatResponse:
        try:
            async with self._mcp.client() as mcp:
                return await asyncio.wait_for(
                    self._run_loop(mcp, messages),
                    timeout=Config.get("chat_server.timeout_seconds"),
                )
        except asyncio.TimeoutError:
            return ChatResponse(answer="The request timed out. Please try a simpler question.")
        except Exception as e:
            logger.error("Orchestration loop failed", exc_info=True)
            raise

    async def _run_loop(self, mcp: MCPClient, user_messages: list[dict]) -> ChatResponse:
        tools = self._mcp.get_tools()
        trace: list[dict] = []

        llm_messages = [
            {"role": "system", "content": Config.get("chat_server.system_prompt")},
            *user_messages,
        ]

        for _ in range(Config.get("chat_server.max_iterations")):
            response = await self._llm.invoke(llm_messages, tools)

            if not response.tool_calls:
                return ChatResponse(
                    answer=response.text or "I wasn't able to generate a response.",
                    tool_calls=trace,
                )

            assistant_content = []
            if response.text:
                assistant_content.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            llm_messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for tc in response.tool_calls:
                try:
                    result_text = await mcp.call_tool(tc.name, tc.arguments)
                except Exception as e:
                    logger.error("Tool call failed", exc_info=True)
                    result_text = json.dumps({"error": "Tool execution failed. Please try a different approach."})

                trace.append({
                    "tool": tc.name,
                    "arguments": tc.arguments,
                    "result": result_text,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result_text,
                })

            llm_messages.append({"role": "user", "content": tool_results})

        return ChatResponse(
            answer="I reached the maximum number of steps. Please try rephrasing your question.",
            tool_calls=trace,
        )
