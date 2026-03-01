import logging

from llm_clients.llm_client import LLMClient
from mcp_client.mcp_client_manager import MCPClientManager
from shared.config import Config
from shared.modules.api.chat_request import ChatRequest
from shared.modules.api.chat_response import ChatResponse
from shared.modules.api.tool_call_event import ToolCallEvent, ToolCallEventStatus
from shared.modules.llm.llm_response import LLMResponse
from shared.modules.llm.tool_call import ToolCall
from shared.modules.llm.messages import (
    AssistantMessage,
    ChatMessage,
    SystemMessage,
    ToolMessage,
    ToolResult,
    UserMessage,
)

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
        self._max_malformed_retries = Config.get("chat_server.max_malformed_retries")
        self._malformed_retry_hint = Config.get("chat_server.malformed_retry_hint")

    async def execute(self, request: ChatRequest) -> ChatResponse:
        messages = self._build_initial_messages(request)
        tools = self._mcp_manager.get_tools()
        tool_call_history: list[ToolCallEvent] = []
        malformed_retries = 0

        for _ in range(self._max_iterations):
            llm_response = await self._llm_client.invoke(messages, tools)

            if llm_response.malformed_function_call:
                malformed_retries += 1
                tool_call_history.append(ToolCallEvent(
                    status=ToolCallEventStatus.MALFORMED,
                    error_message=llm_response.malformed_message,
                    retry_attempt=malformed_retries,
                ))
                if malformed_retries > self._max_malformed_retries:
                    logger.warning("Exceeded max malformed function call retries (%d)", self._max_malformed_retries)
                    return ChatResponse(
                        answer="I was unable to format a valid tool call for this query. "
                               "Please try rephrasing your question or breaking it into simpler parts.",
                        tool_calls=tool_call_history,
                    )
                logger.info("Retrying after malformed function call (attempt %d/%d)", malformed_retries, self._max_malformed_retries)
                messages.append(UserMessage(content=self._malformed_retry_hint))
                continue

            if not llm_response.tool_calls:
                return ChatResponse(
                    answer=llm_response.text or "",
                    tool_calls=tool_call_history,
                )

            messages.append(self._build_assistant_message(llm_response))
            tool_results = await self._execute_tool_calls(llm_response.tool_calls, tool_call_history)
            messages.append(ToolMessage(results=tool_results))

        logger.warning("Max iterations (%d) reached", self._max_iterations)
        return ChatResponse(
            answer="I reached the maximum number of steps. Here is what I found so far.",
            tool_calls=tool_call_history,
        )

    def _build_initial_messages(self, request: ChatRequest) -> list[ChatMessage]:
        messages: list[ChatMessage] = [SystemMessage(content=self._system_prompt)]
        for message in request.messages:
            messages.append(UserMessage(content=message.content))
        return messages

    def _build_assistant_message(self, llm_response: LLMResponse) -> AssistantMessage:
        return AssistantMessage(
            text=llm_response.text,
            tool_calls=llm_response.tool_calls,
        )

    async def _execute_tool_calls(self, tool_calls: list[ToolCall], tool_call_history: list[ToolCallEvent]) -> list[ToolResult]:
        tool_results: list[ToolResult] = []
        for tool_call in tool_calls:
            result = await self._call_single_tool(tool_call)
            tool_call_history.append(ToolCallEvent(
                status=ToolCallEventStatus.ERROR if result.is_error else ToolCallEventStatus.SUCCESS,
                tool=tool_call.name,
                arguments=tool_call.arguments,
                error_message=result.content if result.is_error else None,
            ))
            tool_results.append(result)
        return tool_results

    async def _call_single_tool(self, tool_call: ToolCall) -> ToolResult:
        try:
            async with self._mcp_manager.client() as mcp_client:
                result = await mcp_client.call_tool(tool_call.name, tool_call.arguments)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=result,
            )
        except Exception:
            logger.exception("Tool call failed: %s", tool_call.name)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=f"Error executing {tool_call.name}: tool call failed",
                is_error=True,
            )
