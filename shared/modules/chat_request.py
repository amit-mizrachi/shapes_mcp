from __future__ import annotations

from pydantic import BaseModel, Field

from shared.modules.message_item import MessageItem


class ChatRequest(BaseModel):
    messages: list[MessageItem] = Field(..., min_length=1, max_length=50)
