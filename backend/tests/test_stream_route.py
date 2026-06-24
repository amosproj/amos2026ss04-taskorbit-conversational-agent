"""Tests for POST /v1/conversations/stream (SSE endpoint)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from taskorbit.api.deps import get_current_user_id
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
    app.dependency_overrides[get_current_user_id] = lambda: 1
    app.dependency_overrides[get_session] = _mock_db
    with TestClient(app) as client:
        response = client.post("/v1/conversations/stream", json={"bad": "payload"})
    assert response.status_code == 422
    app.dependency_overrides = {}


# ---------------------------------------------------------------------------
# Auto-create conversation
# ---------------------------------------------------------------------------


def test_stream_conversation_auto_creates_conversation_when_id_absent() -> None:
    """When conversation_id is absent/unknown the endpoint creates one and uses its id."""
    mock_orchestrator = MagicMock()

    new_conv_id = "auto-created-conv-id"
    mock_conv = MagicMock()
    mock_conv.id = new_conv_id

    async def _stream_with_new_id(*tokens: str):
        for token in tokens:
            yield token
        yield ConversationResponse(
            conversation_id=new_conv_id,
            reply=Message(role=MessageRole.ASSISTANT, content="Hi!"),
            status="success",
            selected_intent="general",
            selected_agent="base",
        )

    mock_orchestrator.process_message_stream = MagicMock(return_value=_stream_with_new_id("Hi!"))

    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db
    app.dependency_overrides[get_current_user_id] = lambda: 1

    payload_no_id = {
        "agent_config": {
            "id": "agent-1",
            "name": "Bot",
            "persona": "Helpful",
            "greeting": "Hi!",
        },
        "messages": [{"role": "user", "content": "Hello"}],
    }

    with patch(
        "taskorbit.api.routes.conversations.get_conversation",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with patch(
            "taskorbit.api.routes.conversations.create_conversation",
            new_callable=AsyncMock,
            return_value=mock_conv,
        ):
            with patch(
                "taskorbit.api.routes.conversations.create_conversation_message",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ):
                with TestClient(app) as client:
                    response = client.post("/v1/conversations/stream", json=payload_no_id)

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    assert done_events[0]["conversation_id"] == new_conv_id
    app.dependency_overrides = {}


# ---------------------------------------------------------------------------
# User message persistence
# ---------------------------------------------------------------------------


def test_stream_conversation_saves_user_message_upfront_with_user_id() -> None:
    """User message is saved before streaming begins and carries user_id attribution."""
    mock_orchestrator = MagicMock()
    mock_orchestrator.process_message_stream = MagicMock(
        return_value=_stream_chunks_then_done("ok")
    )

    app = create_app()
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_session] = _mock_db
    app.dependency_overrides[get_current_user_id] = lambda: 99

    save_kwargs: list[dict] = []

    async def _capture_save(**kwargs):  # type: ignore[override]
        save_kwargs.append(kwargs)
        return MagicMock()

    with patch(
        "taskorbit.api.routes.conversations.get_conversation",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ):
        with patch(
            "taskorbit.api.routes.conversations.create_conversation_message",
            side_effect=_capture_save,
        ):
            with TestClient(app) as client:
                response = client.post("/v1/conversations/stream", json=_VALID_PAYLOAD)

    assert response.status_code == 200
    user_saves = [c for c in save_kwargs if c.get("role") == "user"]
    assert len(user_saves) >= 1
    assert user_saves[0]["user_id"] == 99
    app.dependency_overrides = {}
