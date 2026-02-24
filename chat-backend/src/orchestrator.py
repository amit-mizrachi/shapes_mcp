from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from llm.base import LLMClient
from mcp_client import MCPClient, MCPSessionPool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful data analyst assistant. You have access to a database loaded from a CSV file.

IMPORTANT WORKFLOW:
1. ALWAYS call get_schema() first to understand what table, columns, and data types are available.
2. Use select_rows() to retrieve and inspect raw data rows.
3. Use aggregate() for counts, sums, averages, and group-by analysis.
4. Present results clearly and concisely. Use markdown tables when showing tabular data.

Always base your answers on actual query results, not assumptions."""

MAX_ITERATIONS = 10
TIMEOUT_SECONDS = 120


@dataclass
class ToolCallTrace:
    name: str
    arguments: dict
    result: str


@dataclass
class ChatResult:
    answer: str
    tool_calls: list[dict] = field(default_factory=list)


class ChatOrchestrator:
    def __init__(self, llm_client: LLMClient, mcp_pool: MCPSessionPool):
        self._llm = llm_client
        self._mcp_pool = mcp_pool

    async def chat(self, messages: list[dict]) -> ChatResult:
        try:
            async with self._mcp_pool.acquire() as mcp:
                return await asyncio.wait_for(
                    self._run_loop(mcp, messages),
                    timeout=TIMEOUT_SECONDS,
                )
        except asyncio.TimeoutError:
            return ChatResult(answer="The request timed out. Please try a simpler question.")
        except Exception as e:
            logger.error("Orchestrator error: %s", e, exc_info=True)
            raise

    async def _run_loop(self, mcp: MCPClient, user_messages: list[dict]) -> ChatResult:
        tools = self._mcp_pool.get_tools()
        trace: list[dict] = []

        llm_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *user_messages,
        ]

        for _ in range(MAX_ITERATIONS):
            response = await self._llm.invoke(llm_messages, tools)

            if not response.tool_calls:
                return ChatResult(
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
                    logger.error("Tool call %s failed: %s", tc.name, e)
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

        return ChatResult(
            answer="I reached the maximum number of steps. Please try rephrasing your question.",
            tool_calls=trace,
        )
