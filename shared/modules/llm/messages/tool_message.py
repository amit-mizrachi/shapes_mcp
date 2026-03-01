from typing import Literal

from shared.modules.llm.tool_result import ToolResult
from shared.modules.llm.messages.chat_message import ChatMessage


class ToolMessage(ChatMessage):
    role: Literal["tool"] = "tool"
    results: list[ToolResult]
