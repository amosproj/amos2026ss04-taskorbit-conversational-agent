from taskorbit.integrations.llm.messages import (
    to_gemini_contents,
    to_openai_messages,
)
from taskorbit.types import Message, MessageRole


# ---------------------------------------------------------------------------
# to_openai_messages
# ---------------------------------------------------------------------------


def test_openai_translates_user_and_assistant_turns():
    messages = [
        Message(role=MessageRole.USER, content="Hello"),
        Message(role=MessageRole.ASSISTANT, content="Hi there"),
    ]
    result = to_openai_messages(messages)
    assert result == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]


def test_openai_preserves_system_role():
    messages = [
        Message(role=MessageRole.SYSTEM, content="You are helpful."),
        Message(role=MessageRole.USER, content="Hi"),
    ]
    result = to_openai_messages(messages)
    assert result[0] == {"role": "system", "content": "You are helpful."}


def test_openai_empty_list_returns_empty_list():
    assert to_openai_messages([]) == []


# ---------------------------------------------------------------------------
# to_gemini_contents
# ---------------------------------------------------------------------------


def test_gemini_maps_user_to_user_role():
    messages = [Message(role=MessageRole.USER, content="Hello")]
    result = to_gemini_contents(messages)
    assert result == [{"role": "user", "parts": [{"text": "Hello"}]}]


def test_gemini_maps_assistant_to_model_role():
    messages = [Message(role=MessageRole.ASSISTANT, content="Hi there")]
    result = to_gemini_contents(messages)
    assert result == [{"role": "model", "parts": [{"text": "Hi there"}]}]


def test_gemini_drops_system_messages():
    messages = [
        Message(role=MessageRole.SYSTEM, content="You are helpful."),
        Message(role=MessageRole.USER, content="Hi"),
    ]
    result = to_gemini_contents(messages)
    assert len(result) == 1
    assert result[0]["role"] == "user"


def test_gemini_empty_list_returns_empty_list():
    assert to_gemini_contents([]) == []
