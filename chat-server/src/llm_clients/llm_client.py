from abc import ABC, abstractmethod

from shared.modules.llm.llm_response import LLMResponse


class LLMClient(ABC):
    @abstractmethod
    async def invoke(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> LLMResponse:
        ...
