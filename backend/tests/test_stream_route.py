"""Tests for POST /v1/conversations/stream (SSE endpoint)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from taskorbit.api.main import create_app
from taskorbit.api.routes.conversations import get_orchestrator, get_session
from taskorbit.types import ConversationResponse, Message, MessageRole

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
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)
    return db


def _parse_sse_events(text: str) -> list[dict]:
    """Extract and parse all 'data: {...}' lines from an SSE response body."""
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


async def _stream_chunks_then_done(*tokens: str) -> None:
    """Async generator that yields str tokens then a success ConversationResponse."""
    for token in tokens:
        yield token
    yield ConversationResponse(
        conversation_id="conv-1",
        reply=Message(role=MessageRole.ASSISTANT, content="".join(tokens)),
        status="success",
        selected_intent="general",
        selected_agent="base",
    )


async def _stream_error_response() -> None:
    """Async generator that yields only an error ConversationResponse."""
    yield ConversationResponse(
        conversation_id="conv-1",
        reply=Message(role=MessageRole.ASSISTANT, content=""),
        status="error",
        error="LLM config error",
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_stream_conversation_returns_200_with_sse_content_type() -> None:
    mock_orchestrator = MagicMock()
    mock_orchestrator.process_message_stream = MagicMock(
        return_value=_stream_chunks_then_done("Hi!")
    )
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db

    with patch(
        "taskorbit.api.routes.conversations.create_conversation_message",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ):
        with TestClient(app) as client:
            response = client.post("/v1/conversations/stream", json=_VALID_PAYLOAD)

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    app.dependency_overrides = {}


def test_stream_conversation_emits_chunk_events() -> None:
    mock_orchestrator = MagicMock()
    mock_orchestrator.process_message_stream = MagicMock(
        return_value=_stream_chunks_then_done("Hello ", "world!")
    )
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db

    with patch(
        "taskorbit.api.routes.conversations.create_conversation_message",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ):
        with TestClient(app) as client:
            response = client.post("/v1/conversations/stream", json=_VALID_PAYLOAD)

    events = _parse_sse_events(response.text)
    chunk_events = [e for e in events if e["type"] == "chunk"]

    assert len(chunk_events) == 2
    assert chunk_events[0]["text"] == "Hello "
    assert chunk_events[1]["text"] == "world!"
    app.dependency_overrides = {}


def test_stream_conversation_emits_done_event_with_metadata() -> None:
    mock_orchestrator = MagicMock()
    mock_orchestrator.process_message_stream = MagicMock(
        return_value=_stream_chunks_then_done("ok")
    )
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db

    with patch(
        "taskorbit.api.routes.conversations.create_conversation_message",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ):
        with TestClient(app) as client:
            response = client.post("/v1/conversations/stream", json=_VALID_PAYLOAD)

    events = _parse_sse_events(response.text)
    done_events = [e for e in events if e["type"] == "done"]

    assert len(done_events) == 1
    done = done_events[0]
    assert done["status"] == "success"
    assert done["conversation_id"] == "conv-1"
    assert done["intent"] == "general"
    assert done["selected_agent"] == "base"
    app.dependency_overrides = {}


def test_stream_conversation_chunk_events_come_before_done() -> None:
    mock_orchestrator = MagicMock()
    mock_orchestrator.process_message_stream = MagicMock(
        return_value=_stream_chunks_then_done("A", "B")
    )
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db

    with patch(
        "taskorbit.api.routes.conversations.create_conversation_message",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ):
        with TestClient(app) as client:
            response = client.post("/v1/conversations/stream", json=_VALID_PAYLOAD)

    events = _parse_sse_events(response.text)
    types = [e["type"] for e in events]
    assert types.index("done") == len(types) - 1  # done is always last
    app.dependency_overrides = {}


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


def test_stream_conversation_emits_error_event_on_orchestrator_error() -> None:
    mock_orchestrator = MagicMock()
    mock_orchestrator.process_message_stream = MagicMock(return_value=_stream_error_response())
    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db

    with TestClient(app) as client:
        response = client.post("/v1/conversations/stream", json=_VALID_PAYLOAD)

    events = _parse_sse_events(response.text)
    error_events = [e for e in events if e["type"] == "error"]

    assert len(error_events) == 1
    assert "LLM config error" in error_events[0]["message"]
    app.dependency_overrides = {}


def test_stream_conversation_rejects_invalid_payload() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/v1/conversations/stream", json={"bad": "payload"})
    assert response.status_code == 422
