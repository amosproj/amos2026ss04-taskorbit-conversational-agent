"""Tests for POST /v1/conversations/process."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from taskorbit.api.main import create_app
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


def test_process_conversation_returns_501_when_not_implemented() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/v1/conversations/process", json=_VALID_PAYLOAD)
    assert response.status_code == 501


def test_process_conversation_returns_200_with_mock_orchestrator() -> None:
    mock_response = ConversationResponse(
        conversation_id="conv-1",
        reply=Message(role=MessageRole.ASSISTANT, content="Hello back!"),
    )
    app = create_app()
    with patch(
        "taskorbit.api.routes.conversations.ConversationOrchestrator.process_message",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        with TestClient(app) as client:
            response = client.post("/v1/conversations/process", json=_VALID_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conv-1"
    assert body["reply"]["content"] == "Hello back!"


def test_process_conversation_rejects_invalid_payload() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/v1/conversations/process", json={"bad": "payload"})
    assert response.status_code == 422
