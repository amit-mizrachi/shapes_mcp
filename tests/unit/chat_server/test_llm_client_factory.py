"""Tests for chat-server/src/llm_clients/llm_client_factory.py — LLMClientFactory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from llm_clients.claude_llm_client import ClaudeLLMClient
from llm_clients.gemini_llm_client import GeminiLLMClient
from llm_clients.llm_client_factory import LLMClientFactory


class TestCreateLLMClient:
    @patch("llm_clients.llm_client_factory.Config")
    def test_create_claude_client(self, mock_config):
        mock_config.get.side_effect = lambda key: {
            "chat_server.anthropic_model": "claude-sonnet-4-20250514",
            "chat_server.max_tokens": 4096,
        }[key]

        client = LLMClientFactory.create("claude")

        assert isinstance(client, ClaudeLLMClient)
        assert client._model == "claude-sonnet-4-20250514"
        assert client._max_tokens == 4096

    @patch("llm_clients.gemini_llm_client.genai.Client")
    @patch("llm_clients.llm_client_factory.Config")
    def test_create_gemini_client(self, mock_config, _mock_genai):
        mock_config.get.side_effect = lambda key: {
            "chat_server.gemini_model": "gemini-2.5-flash",
            "chat_server.gemini_max_tokens": 8192,
        }[key]

        client = LLMClientFactory.create("gemini")

        assert isinstance(client, GeminiLLMClient)
        assert client._model == "gemini-2.5-flash"
        assert client._max_tokens == 8192

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider: openai"):
            LLMClientFactory.create("openai")
