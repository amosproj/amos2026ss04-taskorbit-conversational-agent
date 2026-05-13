"""Tests for /v1/conversations endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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


def _mock_db() -> MagicMock:
    """Return a mock DB session."""
    db = MagicMock()
    db.query.return_value.order_by.return_value.all.return_value = []
    db.query.return_value.filter.return_value.all.return_value = []
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
    with TestClient(app) as client:
        response = client.get("/v1/conversations/conv-1/messages")
    assert response.status_code == 200
    body = response.json()
    assert "messages" in body
    assert isinstance(body["messages"], list)
    app.dependency_overrides = {}


def test_create_conversation_returns_201() -> None:
    """Verifies that POST /v1/conversations creates a conversation."""
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.commit = MagicMock()
    mock_db.refresh = MagicMock()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: mock_db
    with TestClient(app) as client:
        response = client.post("/v1/conversations")
    assert response.status_code == 201
    app.dependency_overrides = {}
