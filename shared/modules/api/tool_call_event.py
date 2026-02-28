from enum import Enum
from typing import Any, Optional

from shared.modules.shapes_base_model import ShapesBaseModel


class ToolCallEventStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    MALFORMED = "malformed"


class ToolCallEvent(ShapesBaseModel):
    status: ToolCallEventStatus
    tool: Optional[str] = None
    arguments: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    retry_attempt: Optional[int] = None
