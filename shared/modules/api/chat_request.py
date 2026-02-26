from __future__ import annotations

from pydantic import Field

from shared.modules.api.message_item import MessageItem
from shared.modules.shapes_base_model import ShapesBaseModel


class ChatRequest(ShapesBaseModel):
    messages: list[MessageItem] = Field(..., min_length=1, max_length=50)
