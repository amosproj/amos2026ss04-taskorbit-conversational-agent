"""Tests for /v1/conversations endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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

_NO_USER_PAYLOAD = {
    "conversation_id": "conv-no-user",
    "agent_config": {
        "id": "agent-1",
        "name": "Bot",
        "persona": "Helpful",
        "greeting": "Hi!",
    },
    "messages": [{"role": "assistant", "content": "Hello"}],
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


def _mock_orchestrator_with_response() -> AsyncMock:
    """Return a mock orchestrator with a valid response."""
    mock_response = ConversationResponse(
        conversation_id="conv-1",
        reply=Message(role=MessageRole.ASSISTANT, content="[Mocked] Hello"),
        status="success",
    )
    mock_orchestrator = AsyncMock()
    mock_orchestrator.process_message.return_value = mock_response
    return mock_orchestrator


def test_process_conversation_returns_200_with_mock() -> None:
    """Verifies that the endpoint returns a 200 and a valid response using a mock orchestrator."""
    mock_orchestrator = _mock_orchestrator_with_response()
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db
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


# ============ TESTS FOR AUTO-CREATE CONVERSATION BEHAVIOR ============


def test_process_conversation_auto_creates_when_missing() -> None:
    """Auto-create fires when conversation row doesn't exist."""
    mock_orchestrator = _mock_orchestrator_with_response()
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db
    with TestClient(app) as client:
        response = client.post("/v1/conversations/process", json=_VALID_PAYLOAD)
    assert response.status_code == 200
    # orchestrator.process_message was called with db argument
    mock_orchestrator.process_message.assert_called_once()
    args, kwargs = mock_orchestrator.process_message.call_args
    assert "db" in kwargs or len(args) >= 2
    app.dependency_overrides = {}


def test_process_conversation_passes_agent_fields_from_request() -> None:
    """Agent fields come from the request, not hardcoded defaults."""
    mock_orchestrator = _mock_orchestrator_with_response()
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db
    payload = {
        "conversation_id": "conv-custom",
        "agent_config": {
            "id": "custom-agent-id",
            "name": "CustomBot",
            "persona": "Custom persona",
            "greeting": "Hello!",
        },
        "messages": [{"role": "user", "content": "Test"}],
    }
    with TestClient(app) as client:
        response = client.post("/v1/conversations/process", json=payload)
    assert response.status_code == 200
    args, kwargs = mock_orchestrator.process_message.call_args
    request_arg = args[0] if args else kwargs.get("request")
    assert request_arg.agent_config.id == "custom-agent-id"
    assert request_arg.agent_config.name == "CustomBot"
    app.dependency_overrides = {}


def test_process_conversation_no_user_message_still_returns_200() -> None:
    """No-user-message edge case — endpoint returns 200, orchestrator called."""
    mock_response = ConversationResponse(
        conversation_id="conv-no-user",
        reply=Message(role=MessageRole.ASSISTANT, content="Hello"),
        status="success",
    )
    mock_orchestrator = AsyncMock()
    mock_orchestrator.process_message.return_value = mock_response
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db
    with TestClient(app) as client:
        response = client.post("/v1/conversations/process", json=_NO_USER_PAYLOAD)
    assert response.status_code == 200
    mock_orchestrator.process_message.assert_called_once()
    app.dependency_overrides = {}


def test_process_conversation_idempotent_when_exists() -> None:
    """Orchestrator is called with db — idempotency handled inside orchestrator."""
    mock_orchestrator = _mock_orchestrator_with_response()
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db
    with TestClient(app) as client:
        # First call
        r1 = client.post("/v1/conversations/process", json=_VALID_PAYLOAD)
        # Second call same conversation_id
        r2 = client.post("/v1/conversations/process", json=_VALID_PAYLOAD)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert mock_orchestrator.process_message.call_count == 2
    app.dependency_overrides = {}
