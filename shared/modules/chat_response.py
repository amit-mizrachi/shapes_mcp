from __future__ import annotations

from pydantic import BaseModel


class ChatResponse(BaseModel):
    answer: str
    tool_calls: list[dict] = []
