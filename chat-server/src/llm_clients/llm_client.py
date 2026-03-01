from abc import ABC, abstractmethod

from shared.modules.llm.llm_response import LLMResponse
from shared.modules.llm.messages import ChatMessage


class LLMClient(ABC):
    @abstractmethod
    async def invoke(
        self,
        messages: list[ChatMessage],
        tools: list[dict],
    ) -> LLMResponse:
        ...
