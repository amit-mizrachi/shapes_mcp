"""Tests for shared.modules.chat_request.ChatRequest."""

import pytest
from pydantic import ValidationError

from shared.modules.chat_request import ChatRequest
from shared.modules.message_item import MessageItem


class TestChatRequest:
    def test_valid_single_message(self):
        req = ChatRequest(messages=[MessageItem(role="user", content="hello")])
        assert len(req.messages) == 1
        assert req.messages[0].role == "user"

    def test_valid_multiple_messages(self):
        msgs = [MessageItem(role="user", content=f"msg {i}") for i in range(5)]
        req = ChatRequest(messages=msgs)
        assert len(req.messages) == 5

    def test_empty_messages_raises(self):
        with pytest.raises(ValidationError):
            ChatRequest(messages=[])

    def test_too_many_messages_raises(self):
        msgs = [MessageItem(role="user", content="x") for _ in range(51)]
        with pytest.raises(ValidationError):
            ChatRequest(messages=msgs)

    def test_max_messages_allowed(self):
        msgs = [MessageItem(role="user", content="x") for _ in range(50)]
        req = ChatRequest(messages=msgs)
        assert len(req.messages) == 50

    def test_serialization_roundtrip(self):
        req = ChatRequest(messages=[MessageItem(role="user", content="hi")])
        data = req.model_dump()
        restored = ChatRequest(**data)
        assert restored.messages[0].content == "hi"
