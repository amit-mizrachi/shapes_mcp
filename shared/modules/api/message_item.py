from shared.modules.shapes_base_model import ShapesBaseModel


class MessageItem(ShapesBaseModel):
    role: str
    content: str
