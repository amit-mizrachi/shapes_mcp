from shared.config import Config
from llm_clients.llm_client import LLMClient
from llm_clients.claude_llm_client import ClaudeLLMClient
from llm_clients.gemini_llm_client import GeminiLLMClient


class LLMClientFactory:
    @staticmethod
    def create() -> LLMClient:
        provider = Config.get("chat_server.llm_provider")
        if provider == "claude":
            return ClaudeLLMClient()
        if provider == "gemini":
            return GeminiLLMClient()
        raise ValueError(f"Unknown LLM provider: {provider}")
