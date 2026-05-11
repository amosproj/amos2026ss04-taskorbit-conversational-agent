"""Tests for the LiveKit local worker entrypoint (taskorbit/worker.py).

Covers:
  1. entrypoint() connects to the room and calls session.start().
  2. A valid "commit_turn" data message triggers request_reply() + generate_reply().
  3. Malformed JSON packets are silently ignored.
  4. Unrecognised message types are silently ignored.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.config import get_settings
from taskorbit.worker import entrypoint


@pytest.fixture
def configured_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("LIVEKIT_URL", "ws://test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "secret")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-test-key")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test-key")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _make_ctx() -> tuple[MagicMock, dict[str, object]]:
    """Return a mock JobContext and a dict that captures registered room handlers."""
    registered: dict[str, object] = {}

    def fake_room_on(event: str):  # type: ignore[return]
        def decorator(fn):  # type: ignore[return]
            registered[event] = fn
            return fn

        return decorator

    ctx = MagicMock()
    ctx.connect = AsyncMock()
    ctx.room.on.side_effect = fake_room_on
    return ctx, registered


def _data_packet(payload: bytes) -> MagicMock:
    packet = MagicMock()
    packet.data = payload
    return packet


@pytest.mark.asyncio
async def test_entrypoint_starts_session(configured_settings: None) -> None:
    """entrypoint() should connect, build session/agent, and call session.start()."""
    ctx, _ = _make_ctx()
    mock_session = AsyncMock()
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
    ):
        await entrypoint(ctx)

    ctx.connect.assert_awaited_once()
    mock_session.start.assert_awaited_once()
    call_kwargs = mock_session.start.call_args
    assert call_kwargs.args[0] is mock_agent
    assert call_kwargs.kwargs["room"] is ctx.room


@pytest.mark.asyncio
async def test_commit_turn_triggers_reply(configured_settings: None) -> None:
    """A "commit_turn" data message should call request_reply() then generate_reply()."""
    ctx, registered = _make_ctx()
    mock_session = AsyncMock()
    mock_session.generate_reply = MagicMock(return_value=None)
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
    ):
        await entrypoint(ctx)

    handler = registered["data_received"]
    packet = _data_packet(json.dumps({"type": "commit_turn"}).encode())
    handler(packet)

    mock_agent.request_reply.assert_called_once()
    mock_session.generate_reply.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_json_ignored(configured_settings: None) -> None:
    """Malformed JSON in a data packet should be silently ignored."""
    ctx, registered = _make_ctx()
    mock_session = AsyncMock()
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
    ):
        await entrypoint(ctx)

    handler = registered["data_received"]
    handler(_data_packet(b"not valid json{{"))

    mock_agent.request_reply.assert_not_called()


@pytest.mark.asyncio
async def test_entrypoint_says_greeting_from_metadata(configured_settings: None) -> None:
    """Greeting from participant metadata is spoken via session.say()."""
    ctx, _ = _make_ctx()
    participant = MagicMock()
    participant.metadata = json.dumps({"greeting": "Hi from frontend!"})
    ctx.room.remote_participants = {"user-1": participant}

    mock_session = AsyncMock()
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
    ):
        await entrypoint(ctx)

    mock_session.say.assert_awaited_once_with("Hi from frontend!")


@pytest.mark.asyncio
async def test_entrypoint_says_default_greeting_when_no_metadata(configured_settings: None) -> None:
    """Falls back to 'Hello!' when no participant metadata is present."""
    ctx, _ = _make_ctx()
    ctx.room.remote_participants = {}

    mock_session = AsyncMock()
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
    ):
        await entrypoint(ctx)

    mock_session.say.assert_awaited_once_with("Hello!")


@pytest.mark.asyncio
async def test_unknown_message_type_ignored(configured_settings: None) -> None:
    """A data packet with an unrecognised type should not trigger a reply."""
    ctx, registered = _make_ctx()
    mock_session = AsyncMock()
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
    ):
        await entrypoint(ctx)

    handler = registered["data_received"]
    handler(_data_packet(json.dumps({"type": "ping"}).encode()))

    mock_agent.request_reply.assert_not_called()
