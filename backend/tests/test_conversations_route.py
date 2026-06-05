"""Tests for /v1/conversations endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from taskorbit.api.deps import get_current_user_id
from taskorbit.api.main import create_app
from taskorbit.api.routes.conversations import get_orchestrator, get_session
from taskorbit.types import (
    ConversationResponse,
    Message,
    MessageRole,
    ToolDefinition,
    ToolType,
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
    app.dependency_overrides[get_current_user_id] = lambda: 1
    with (
        patch(
            "taskorbit.api.routes.conversations.get_conversation",
            new_callable=AsyncMock,
            return_value=MagicMock(),  # truthy — conversation exists, skip auto-create
        ),
        patch(
            "taskorbit.api.routes.conversations.create_conversation_message",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        with TestClient(app) as client:
            response = client.post("/v1/conversations/process", json=_VALID_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conv-1"
    assert "[Mocked] Hello" == body["reply"]["content"]
    assert body["reply"]["role"] == "assistant"
    app.dependency_overrides = {}


def test_process_conversation_auto_creates_when_no_id() -> None:
    """When no conversation_id is sent the endpoint auto-creates one and returns the assigned ID."""
    new_conv_id = "auto-conv-abc123"
    mock_conv = MagicMock()
    mock_conv.id = new_conv_id

    mock_response = ConversationResponse(
        conversation_id=new_conv_id,
        reply=Message(role=MessageRole.ASSISTANT, content="Hello!"),
        status="success",
    )
    mock_orchestrator = AsyncMock()
    mock_orchestrator.process_message.return_value = mock_response

    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db
    app.dependency_overrides[get_current_user_id] = lambda: 1

    payload = {
        "agent_config": {
            "id": "agent-1",
            "name": "Bot",
            "persona": "Helpful",
            "greeting": "Hi!",
        },
        "messages": [{"role": "user", "content": "Hello"}],
    }

    with (
        patch(
            "taskorbit.api.routes.conversations.get_conversation",
            new_callable=AsyncMock,
            return_value=None,  # simulates unknown / first-ever conversation
        ),
        patch(
            "taskorbit.api.routes.conversations.create_conversation",
            new_callable=AsyncMock,
            return_value=mock_conv,
        ),
        patch(
            "taskorbit.api.routes.conversations.create_conversation_message",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        with TestClient(app) as client:
            response = client.post("/v1/conversations/process", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == new_conv_id
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


def test_get_history_returns_200() -> None:
    """GET /v1/conversations/{id}/history returns the full history payload."""
    history_payload = {
        "conversation_id": "conv-1",
        "agent_id": "agent-1",
        "agent_name": "Bot",
        "started_at": "2026-06-05T20:00:00+00:00",
        "ended_at": None,
        "messages": [
            {"id": 1, "role": "user", "content": "Hi", "created_at": "2026-06-05T20:00:01+00:00"},
            {
                "id": 2,
                "role": "assistant",
                "content": "Hello!",
                "created_at": "2026-06-05T20:00:02+00:00",
            },
        ],
        "tool_executions": [
            {
                "id": 1,
                "tool_id": "data_extraction",
                "tool_type": "extraction",
                "confirmed": False,
                "executed_at": "2026-06-05T20:00:02+00:00",
                "result": {"extracted_slots": {"name": "Alice"}},
            }
        ],
        "slot_extractions": [
            {
                "id": 1,
                "tool_id": "data_extraction",
                "field_name": "name",
                "field_value": "Alice",
                "extracted_at": "2026-06-05T20:00:02+00:00",
            }
        ],
    }
    app = create_app()
    app.dependency_overrides[get_session] = _mock_db
    with patch(
        "taskorbit.api.routes.conversations.get_conversation_history",
        new_callable=AsyncMock,
        return_value=history_payload,
    ):
        with TestClient(app) as client:
            response = client.get("/v1/conversations/conv-1/history")
    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conv-1"
    assert body["agent_name"] == "Bot"
    assert len(body["messages"]) == 2
    assert len(body["tool_executions"]) == 1
    assert body["tool_executions"][0]["tool_id"] == "data_extraction"
    assert len(body["slot_extractions"]) == 1
    assert body["slot_extractions"][0]["field_name"] == "name"
    assert body["slot_extractions"][0]["tool_id"] == "data_extraction"
    app.dependency_overrides = {}


def test_get_history_returns_404_when_not_found() -> None:
    """GET /v1/conversations/{id}/history returns 404 for unknown conversation."""
    app = create_app()
    app.dependency_overrides[get_session] = _mock_db
    with patch(
        "taskorbit.api.routes.conversations.get_conversation_history",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with TestClient(app) as client:
            response = client.get("/v1/conversations/nonexistent/history")
    assert response.status_code == 404
    app.dependency_overrides = {}


def test_process_conversation_persists_slot_extractions() -> None:
    """When the orchestrator returns extracted_slots, create_slot_extractions is called once."""
    tool = ToolDefinition(
        id="data_extraction",
        name="collect_info",
        type=ToolType.DATA_EXTRACTION,
        description="Collects user info",
    )
    mock_response = ConversationResponse(
        conversation_id="conv-1",
        reply=Message(role=MessageRole.ASSISTANT, content="Got it!"),
        status="success",
        tool_invoked=tool,
        extracted_slots={"name": "Alice", "email": "alice@example.com"},
    )
    mock_orchestrator = AsyncMock()
    mock_orchestrator.process_message.return_value = mock_response

    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db
    app.dependency_overrides[get_current_user_id] = lambda: 1

    with (
        patch(
            "taskorbit.api.routes.conversations.get_conversation",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
        patch(
            "taskorbit.api.routes.conversations.create_conversation_message",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "taskorbit.api.routes.conversations.create_slot_extractions",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_extractions,
        patch(
            "taskorbit.api.routes.conversations.create_tool_execution",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        with TestClient(app) as client:
            response = client.post("/v1/conversations/process", json=_VALID_PAYLOAD)

    assert response.status_code == 200
    mock_extractions.assert_called_once()
    call_kwargs = mock_extractions.call_args.kwargs
    assert call_kwargs["tool_id"] == "data_extraction"
    assert call_kwargs["slots"] == {"name": "Alice", "email": "alice@example.com"}
    app.dependency_overrides = {}


def test_process_conversation_records_tool_execution() -> None:
    """When the orchestrator returns tool_invoked, create_tool_execution is called once."""
    tool = ToolDefinition(
        id="agent_transfer",
        name="transfer",
        type=ToolType.AGENT_TRANSFER,
        description="Transfers the call",
    )
    mock_response = ConversationResponse(
        conversation_id="conv-1",
        reply=Message(role=MessageRole.ASSISTANT, content="Transferring now."),
        status="success",
        tool_invoked=tool,
    )
    mock_orchestrator = AsyncMock()
    mock_orchestrator.process_message.return_value = mock_response

    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db
    app.dependency_overrides[get_current_user_id] = lambda: 1

    with (
        patch(
            "taskorbit.api.routes.conversations.get_conversation",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
        patch(
            "taskorbit.api.routes.conversations.create_conversation_message",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "taskorbit.api.routes.conversations.create_tool_execution",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_execution,
    ):
        with TestClient(app) as client:
            response = client.post("/v1/conversations/process", json=_VALID_PAYLOAD)

    assert response.status_code == 200
    mock_execution.assert_called_once()
    call_kwargs = mock_execution.call_args.kwargs
    assert call_kwargs["tool_id"] == "agent_transfer"
    assert call_kwargs["tool_type"] == ToolType.AGENT_TRANSFER.value
    app.dependency_overrides = {}
