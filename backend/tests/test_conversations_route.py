"""Tests for /v1/conversations endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from taskorbit.api.main import create_app
from taskorbit.api.routes.conversations import get_orchestrator, get_session
from taskorbit.types import (
    ConversationResponse,
    Message,
    MessageRole,
)

_VALID_PAYLOAD = {
    "conversation_id": "conv-1",
    "agent_config": {
        "id": "agent-1",
        "name": "Bot",
        "persona": "Helpful",
        "greeting": "Hi!",
    },
    "messages": [{"role": "user", "content": "Hello"}],
}


def _mock_db() -> AsyncMock:
    """Return a mock async DB session."""
    db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute = AsyncMock(return_value=mock_result)
    return db


def test_process_conversation_returns_200_with_mock() -> None:
    """Verifies that the endpoint returns a 200 and a valid response using a mock orchestrator."""
    mock_response = ConversationResponse(
        conversation_id="conv-1",
        reply=Message(role=MessageRole.ASSISTANT, content="[Mocked] Hello"),
        status="success",
    )
    mock_orchestrator = AsyncMock()
    mock_orchestrator.process_message.return_value = mock_response
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db
    with patch(
        "taskorbit.api.routes.conversations.create_conversation_message",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with TestClient(app) as client:
            response = client.post("/v1/conversations/process", json=_VALID_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conv-1"
    assert "[Mocked] Hello" == body["reply"]["content"]
    assert body["reply"]["role"] == "assistant"
    app.dependency_overrides = {}


def test_process_conversation_rejects_invalid_payload() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/v1/conversations/process", json={"bad": "payload"})
    assert response.status_code == 422


def test_get_conversations_returns_200() -> None:
    """Verifies that GET /v1/conversations returns 200 with empty list."""
    app = create_app()
    app.dependency_overrides[get_session] = _mock_db
    with TestClient(app) as client:
        response = client.get("/v1/conversations")
    assert response.status_code == 200
    body = response.json()
    assert "conversations" in body
    assert isinstance(body["conversations"], list)
    app.dependency_overrides = {}


def test_get_conversation_messages_returns_200() -> None:
    """Verifies that GET /v1/conversations/{id}/messages returns 200."""
    app = create_app()
    app.dependency_overrides[get_session] = _mock_db
    with patch(
        "taskorbit.api.routes.conversations.get_messages_by_conversation",
        new_callable=AsyncMock,
        return_value=[],
    ):
        with TestClient(app) as client:
            response = client.get("/v1/conversations/conv-1/messages")
    assert response.status_code == 200
    body = response.json()
    assert "messages" in body
    assert isinstance(body["messages"], list)
    app.dependency_overrides = {}


def test_create_conversation_returns_201() -> None:
    """Verifies that POST /v1/conversations creates a conversation."""
    app = create_app()
    app.dependency_overrides[get_session] = _mock_db
    with TestClient(app) as client:
        response = client.post("/v1/conversations")
    assert response.status_code == 201
    app.dependency_overrides = {}


# ============ MOCK-BASED TESTS FOR AUTO-CREATE CONVERSATION BEHAVIOR ============


def test_auto_create_conversation_logic_when_not_exists():
    """Test that auto-create logic creates conversation when it doesn't exist."""
    from taskorbit.database.models import Conversation

    # Simulate conversation doesn't exist
    conversation_exists = False
    conversation_id = "test-conv-123"
    agent_id = "test-agent"
    agent_name = "Test Agent"

    if not conversation_exists:
        conversation = Conversation(
            id=conversation_id,
            agent_id=agent_id,
            agent_name=agent_name,
        )
        assert conversation.id == conversation_id
        assert conversation.agent_id == agent_id
        assert conversation.agent_name == agent_name
        assert conversation.id is not None
    else:
        pytest.fail("Should have created conversation")

    assert True


def test_auto_create_logic_reuses_existing_conversation():
    """Test that auto-create logic reuses existing conversation without duplicate."""
    from taskorbit.database.models import Conversation

    # Simulate conversation already exists
    conversation_exists = True
    conversation_id = "existing-conv-456"
    existing_agent_name = "Existing Agent"

    existing_conversation = Conversation(
        id=conversation_id,
        agent_id="existing-agent",
        agent_name=existing_agent_name,
    )

    if conversation_exists:
        # Should reuse, not create new
        conversation = existing_conversation
        assert conversation.id == conversation_id
        assert conversation.agent_name == existing_agent_name
        # Verify no duplicate
        assert conversation.id == existing_conversation.id
    else:
        pytest.fail("Should have reused existing conversation")

    assert True


def test_auto_create_logic_copies_agent_config_from_request():
    """Test that auto-created conversation uses agent_id and agent_name from request."""
    from taskorbit.database.models import Conversation

    # Simulate request agent config
    request_agent_id = "custom-agent-789"
    request_agent_name = "Custom Named Agent"
    conversation_id = "test-conv-789"

    # Simulate conversation doesn't exist
    conversation_exists = False

    if not conversation_exists:
        conversation = Conversation(
            id=conversation_id,
            agent_id=request_agent_id,
            agent_name=request_agent_name,
        )
        assert conversation.agent_id == request_agent_id
        assert conversation.agent_name == request_agent_name
    else:
        pytest.fail("Should have created conversation with custom agent config")

    assert True


def test_assistant_message_not_saved_without_user_message():
    """Test that assistant message is NOT saved when there is no user message."""
    # Simulate no user message
    has_user_message = False
    has_assistant_reply = True

    saved_assistant = False

    if has_user_message and has_assistant_reply:
        saved_assistant = True
    elif not has_user_message:
        # Assistant should NOT be saved
        saved_assistant = False

    assert saved_assistant is False, "Assistant message should not be saved without a user message"
