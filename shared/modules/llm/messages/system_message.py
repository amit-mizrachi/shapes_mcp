from typing import Literal

from shared.modules.llm.messages.chat_message import ChatMessage


class SystemMessage(ChatMessage):
    role: Literal["system"] = "system"
    content: str
