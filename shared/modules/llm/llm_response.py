from typing import Optional

from shared.modules.llm.tool_call import ToolCall
from shared.modules.shapes_base_model import ShapesBaseModel


class LLMResponse(ShapesBaseModel):
    text: Optional[str] = None
    tool_calls: list[ToolCall] = []
    malformed_function_call: bool = False
    malformed_message: Optional[str] = None
