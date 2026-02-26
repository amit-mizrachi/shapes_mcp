from __future__ import annotations

from shared.modules.shapes_base_model import ShapesBaseModel


class ChatResponse(ShapesBaseModel):
    answer: str
    tool_calls: list[dict] = []
