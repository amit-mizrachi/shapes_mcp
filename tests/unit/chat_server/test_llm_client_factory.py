"""Tests for chat-server/src/llm_clients/llm_client_factory.py — LLMClientFactory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from llm_clients.claude_llm_client import ClaudeLLMClient
from llm_clients.gemini_llm_client import GeminiLLMClient
from llm_clients.llm_client_factory import LLMClientFactory


class TestCreateLLMClient:
    @patch("llm_clients.claude_llm_client.anthropic")
    @patch("llm_clients.llm_client_factory.Config")
    def test_create_claude_client(self, mock_config, _mock_anthropic):
        mock_config.get.return_value = "claude"
        client = LLMClientFactory.create()
        assert isinstance(client, ClaudeLLMClient)

    @patch("llm_clients.gemini_llm_client.genai")
    @patch("llm_clients.llm_client_factory.Config")
    def test_create_gemini_client(self, mock_config, _mock_genai):
        mock_config.get.return_value = "gemini"
        client = LLMClientFactory.create()
        assert isinstance(client, GeminiLLMClient)

    @patch("llm_clients.llm_client_factory.Config")
    def test_unknown_provider_raises(self, mock_config):
        mock_config.get.return_value = "openai"
        with pytest.raises(ValueError, match="Unknown LLM provider: openai"):
            LLMClientFactory.create()
