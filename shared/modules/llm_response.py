from __future__ import annotations

from dataclasses import dataclass, field

from shared.modules.tool_call import ToolCall


@dataclass
class LLMResponse:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
