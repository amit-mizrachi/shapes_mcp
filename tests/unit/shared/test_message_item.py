"""Tests for shared.modules.message_item.MessageItem."""

from shared.modules.message_item import MessageItem


class TestMessageItem:
    def test_user_message(self):
        msg = MessageItem(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"

    def test_assistant_message(self):
        msg = MessageItem(role="assistant", content="hi there")
        assert msg.role == "assistant"

    def test_serialization(self):
        msg = MessageItem(role="user", content="test")
        data = msg.model_dump()
        assert data == {"role": "user", "content": "test"}

    def test_from_dict(self):
        msg = MessageItem(**{"role": "user", "content": "hey"})
        assert msg.content == "hey"
