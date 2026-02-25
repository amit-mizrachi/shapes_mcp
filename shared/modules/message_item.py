from __future__ import annotations

from pydantic import BaseModel


class MessageItem(BaseModel):
    role: str
    content: str
