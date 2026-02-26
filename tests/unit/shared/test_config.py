"""Tests for shared.config.Config."""

import pytest

from shared.config import Config


class TestConfig:
    def test_get_existing_key(self):
        assert Config.get("shared.log_level") == "INFO"

    def test_get_numeric_key(self):
        assert Config.get("shared.default_query_limit") == 20

    def test_get_mcp_server_port(self):
        assert Config.get("mcp_server.port") == 3001

    def test_get_numeric_threshold(self):
        assert Config.get("mcp_server.numeric_threshold") == 0.8

    def test_get_chat_server_list(self):
        origins = Config.get("chat_server.cors_origins")
        assert isinstance(origins, list)
        assert "http://localhost:3000" in origins

    def test_get_missing_key_raises(self):
        with pytest.raises(KeyError):
            Config.get("nonexistent.key")

    def test_get_system_prompt_is_string(self):
        prompt = Config.get("chat_server.system_prompt")
        assert isinstance(prompt, str)
        assert len(prompt) > 0
