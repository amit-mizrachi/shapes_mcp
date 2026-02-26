from __future__ import annotations

from shared.config import Config
from llm_clients.llm_client_interface import LLMClientInterface
from llm_clients.claude_llm_client import ClaudeLLMClient
from llm_clients.gemini_llm_client import GeminiLLMClient


class LLMClientFactory:
    @staticmethod
    def create(provider: str) -> LLMClientInterface:
        if provider == "claude":
            return ClaudeLLMClient(
                model=Config.get("chat_server.anthropic_model"),
                max_tokens=Config.get("chat_server.max_tokens"),
            )
        if provider == "gemini":
            return GeminiLLMClient(
                model=Config.get("chat_server.gemini_model"),
                max_tokens=Config.get("chat_server.gemini_max_tokens"),
            )
        raise ValueError(f"Unknown LLM provider: {provider}")
