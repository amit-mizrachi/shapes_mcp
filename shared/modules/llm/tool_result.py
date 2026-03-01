from shared.modules.shapes_base_model import ShapesBaseModel


class ToolResult(ShapesBaseModel):
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False
