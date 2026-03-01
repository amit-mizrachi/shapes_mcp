from typing import Literal

from pydantic import Field, model_validator

from shared.modules.llm.tool_call import ToolCall
from shared.modules.llm.messages.chat_message import ChatMessage


class AssistantMessage(ChatMessage):
    role: Literal["assistant"] = "assistant"
    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def _must_have_content(self) -> "AssistantMessage":
        if not self.text and not self.tool_calls:
            raise ValueError("AssistantMessage must have text or tool_calls")
        return self
