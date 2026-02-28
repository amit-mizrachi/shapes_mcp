from shared.modules.api.tool_call_event import ToolCallEvent
from shared.modules.shapes_base_model import ShapesBaseModel


class ChatResponse(ShapesBaseModel):
    answer: str
    tool_calls: list[ToolCallEvent] = []
