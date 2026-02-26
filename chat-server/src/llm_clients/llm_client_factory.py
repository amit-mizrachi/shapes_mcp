from __future__ import annotations

from shared.config import Config
from llm_clients.base_llm_client import BaseLLMClient
from llm_clients.claude_llm_client import ClaudeLLMClient
from llm_clients.gemini_llm_client import GeminiLLMClient

_REGISTRY: dict[str, tuple[type[BaseLLMClient], str, str]] = {
    "claude": (ClaudeLLMClient, "chat_server.anthropic_model", "chat_server.max_tokens"),
    "gemini": (GeminiLLMClient, "chat_server.gemini_model", "chat_server.gemini_max_tokens"),
}


def create_llm_client(provider: str) -> BaseLLMClient:
    if provider not in _REGISTRY:
        raise ValueError(f"Unknown LLM provider: {provider}")
    cls, model_key, max_tokens_key = _REGISTRY[provider]
    return cls(model=Config.get(model_key), max_tokens=Config.get(max_tokens_key))
