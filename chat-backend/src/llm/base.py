from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(ABC):
    @abstractmethod
    async def invoke(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> LLMResponse:
        """Send messages + tool definitions to the LLM, return response."""
        ...
