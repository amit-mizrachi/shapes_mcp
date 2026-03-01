from typing import Literal

from shared.modules.llm.messages.chat_message import ChatMessage


class UserMessage(ChatMessage):
    role: Literal["user"] = "user"
    content: str
