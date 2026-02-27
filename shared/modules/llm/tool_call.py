from shared.modules.shapes_base_model import ShapesBaseModel


class ToolCall(ShapesBaseModel):
    id: str
    name: str
    arguments: dict
