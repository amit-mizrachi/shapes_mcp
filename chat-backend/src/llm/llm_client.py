from __future__ import annotations

from abc import ABC, abstractmethod

from shared.modules.llm_response import LLMResponse


class LLMClient(ABC):
    @abstractmethod
    async def invoke(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> LLMResponse:
        ...
