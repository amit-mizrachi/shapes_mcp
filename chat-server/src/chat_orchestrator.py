import logging

from llm_clients.llm_client import LLMClient
from mcp_client.mcp_client_manager import MCPClientManager
from shared.config import Config
from shared.modules.api.chat_request import ChatRequest
from shared.modules.api.chat_response import ChatResponse
from shared.modules.llm.llm_response import LLMResponse
from shared.modules.llm.tool_call import ToolCall

logger = logging.getLogger(__name__)


class ChatOrchestrator:
    def __init__(
        self,
        llm_client: LLMClient,
        mcp_manager: MCPClientManager,
    ):
        self._llm_client = llm_client
        self._mcp_manager = mcp_manager
        self._system_prompt = Config.get("chat_server.system_prompt")
        self._max_iterations = Config.get("chat_server.max_iterations")

    async def execute(self, request: ChatRequest) -> ChatResponse:
        messages = self._build_initial_messages(request)
        tools = self._mcp_manager.get_tools()
        tool_call_history: list[dict] = []

        for _ in range(self._max_iterations):
            llm_response = await self._llm_client.invoke(messages, tools)

            if not llm_response.tool_calls:
                return ChatResponse(
                    answer=llm_response.text or "",
                    tool_calls=tool_call_history,
                )

            messages.append(self._build_assistant_message(llm_response))
            tool_results = await self._execute_tool_calls(llm_response.tool_calls, tool_call_history)
            messages.append({"role": "tool", "content": tool_results})

        logger.warning("Max iterations (%d) reached", self._max_iterations)
        return ChatResponse(
            answer="I reached the maximum number of steps. Here is what I found so far.",
            tool_calls=tool_call_history,
        )

    def _build_initial_messages(self, request: ChatRequest) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": self._system_prompt}]
        for msg in request.messages:
            messages.append({"role": msg.role, "content": msg.content})
        return messages

    def _build_assistant_message(self, llm_response: LLMResponse) -> dict:
        content: list[dict] = []
        if llm_response.text:
            content.append({"type": "text", "text": llm_response.text})
        for tool_call in llm_response.tool_calls:
            content.append({
                "type": "tool_call",
                "id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
            })
        return {"role": "assistant", "content": content}

    async def _execute_tool_calls(self, tool_calls: list[ToolCall], tool_call_history: list[dict]) -> list[dict]:
        tool_results: list[dict] = []
        for tool_call in tool_calls:
            tool_call_history.append({"tool": tool_call.name, "arguments": tool_call.arguments})
            result = await self._call_single_tool(tool_call)
            tool_results.append(result)
        return tool_results

    async def _call_single_tool(self, tool_call: ToolCall) -> dict:
        try:
            async with self._mcp_manager.client() as mcp_client:
                result = await mcp_client.call_tool(tool_call.name, tool_call.arguments)
            return {
                "type": "tool_result",
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "content": result,
            }
        except Exception:
            logger.exception("Tool call failed: %s", tool_call.name)
            return {
                "type": "tool_result",
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "content": f"Error executing {tool_call.name}: tool call failed",
                "is_error": True,
            }
