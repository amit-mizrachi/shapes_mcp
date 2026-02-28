from enum import Enum
from typing import Any

from shared.modules.shapes_base_model import ShapesBaseModel


class ToolCallEventStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    MALFORMED = "malformed"


class ToolCallEvent(ShapesBaseModel):
    status: ToolCallEventStatus
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    error_message: str | None = None
    retry_attempt: int | None = None
