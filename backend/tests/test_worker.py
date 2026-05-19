"""Tests for the LiveKit local worker entrypoint (taskorbit/worker.py).

Covers:
  1. entrypoint() connects to the room and calls session.start().
  2. A valid "commit_turn" data message triggers request_reply() + generate_reply().
  3. Malformed JSON packets are silently ignored.
  4. Unrecognised message types are silently ignored.
  5. "interrupt_playback" calls session.interrupt().
  6. "interrupt_playback" arriving while a reply task is pending cancels the task
     so generate_reply() is never called for that stale turn.
  7. A completed reply task is not double-cancelled on a subsequent interrupt.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.config import get_settings
from taskorbit.worker import entrypoint


def _make_tts_metrics(
    ttfb: float = 0.12, duration: float = 1.5, audio_duration: float = 1.8
) -> MagicMock:
    from livekit.agents.metrics import TTSMetrics

    m = MagicMock(spec=TTSMetrics)
    m.ttfb = ttfb
    m.duration = duration
    m.audio_duration = audio_duration
    m.cancelled = False
    return m


def _make_stt_metrics(duration: float = 0.25, audio_duration: float = 2.0) -> MagicMock:
    from livekit.agents.metrics import STTMetrics

    m = MagicMock(spec=STTMetrics)
    m.duration = duration
    m.audio_duration = audio_duration
    return m


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


def _make_session_mock() -> AsyncMock:
    """Return an AsyncMock session where .on() acts as a synchronous decorator factory.

    AgentSession.on() is synchronous (not a coroutine) — it registers a callback
    and returns the decorator. AsyncMock makes child attributes AsyncMocks by default,
    which means session.on(...) would return a coroutine instead of a callable.
    Replacing it with a plain MagicMock preserves the synchronous decorator pattern.
    """
    session = AsyncMock()
    session.on = MagicMock(side_effect=lambda event: (lambda fn: fn))
    return session


def _data_packet(payload: bytes, participant_identity: str = "remote-user") -> MagicMock:
    packet = MagicMock()
    packet.data = payload
    packet.participant = MagicMock()
    packet.participant.identity = participant_identity
    return packet


def _server_packet(payload: bytes) -> MagicMock:
    """Simulate a server-SDK packet where participant is None."""
    packet = MagicMock()
    packet.data = payload
    packet.participant = None
    return packet


@pytest.mark.asyncio
async def test_entrypoint_starts_session(configured_settings: None) -> None:
    """entrypoint() should connect, build session/agent, and call session.start()."""
    ctx, _ = _make_ctx()
    mock_session = _make_session_mock()
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
    mock_session = _make_session_mock()
    mock_session.generate_reply = MagicMock(return_value=None)
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
        patch("taskorbit.worker._DEEPGRAM_FLUSH_DELAY_S", 0),
    ):
        await entrypoint(ctx)

        handler = registered["data_received"]
        packet = _data_packet(json.dumps({"type": "commit_turn"}).encode())
        handler(packet)
        await asyncio.sleep(0)  # start _commit_and_reply task
        await asyncio.sleep(0)  # complete past its inner sleep(0)

        mock_agent.request_reply.assert_called_once()
        mock_session.generate_reply.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_json_ignored(configured_settings: None) -> None:
    """Malformed JSON in a data packet should be silently ignored."""
    ctx, registered = _make_ctx()
    mock_session = _make_session_mock()
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
async def test_unknown_message_type_ignored(configured_settings: None) -> None:
    """A data packet with an unrecognised type should not trigger a reply."""
    ctx, registered = _make_ctx()
    mock_session = _make_session_mock()
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
    ):
        await entrypoint(ctx)

    handler = registered["data_received"]
    handler(_data_packet(json.dumps({"type": "ping"}).encode()))

    mock_agent.request_reply.assert_not_called()


@pytest.mark.asyncio
async def test_server_packet_ignored(configured_settings: None) -> None:
    """A packet with participant=None (server-SDK origin) should be silently ignored."""
    ctx, registered = _make_ctx()
    mock_session = _make_session_mock()
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
    ):
        await entrypoint(ctx)

    handler = registered["data_received"]
    handler(_server_packet(json.dumps({"type": "commit_turn"}).encode()))

    mock_agent.request_reply.assert_not_called()


@pytest.mark.asyncio
async def test_interrupt_playback_calls_session_interrupt(configured_settings: None) -> None:
    """An "interrupt_playback" message should call session.interrupt() immediately."""
    ctx, registered = _make_ctx()
    mock_session = _make_session_mock()
    mock_session.interrupt = MagicMock()
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
    ):
        await entrypoint(ctx)

    handler = registered["data_received"]
    handler(_data_packet(json.dumps({"type": "interrupt_playback"}).encode()))

    mock_session.interrupt.assert_called_once()
    mock_agent.request_reply.assert_not_called()


@pytest.mark.asyncio
async def test_commit_turn_does_not_call_interrupt(configured_settings: None) -> None:
    """A "commit_turn" message must not trigger session.interrupt()."""
    ctx, registered = _make_ctx()
    mock_session = _make_session_mock()
    mock_session.generate_reply = MagicMock(return_value=None)
    mock_session.interrupt = MagicMock()
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
        patch("taskorbit.worker._DEEPGRAM_FLUSH_DELAY_S", 0),
    ):
        await entrypoint(ctx)

        handler = registered["data_received"]
        handler(_data_packet(json.dumps({"type": "commit_turn"}).encode()))
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    mock_session.interrupt.assert_not_called()


@pytest.mark.asyncio
async def test_interrupt_session_exception_is_logged(configured_settings: None) -> None:
    """session.interrupt() failure should be caught and logged, not propagated."""
    ctx, registered = _make_ctx()
    mock_session = _make_session_mock()
    mock_session.interrupt = MagicMock(side_effect=RuntimeError("tts already stopped"))
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
    ):
        await entrypoint(ctx)

    handler = registered["data_received"]
    handler(_data_packet(json.dumps({"type": "interrupt_playback"}).encode()))


@pytest.mark.asyncio
async def test_interrupt_cancels_pending_reply_task(configured_settings: None) -> None:
    """interrupt_playback arriving before _commit_and_reply completes must cancel
    the task so generate_reply() is never called for the stale turn."""
    ctx, registered = _make_ctx()
    mock_session = _make_session_mock()
    mock_session.generate_reply = MagicMock(return_value=None)
    mock_session.interrupt = MagicMock()
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
        patch("taskorbit.worker._DEEPGRAM_FLUSH_DELAY_S", 0),
    ):
        await entrypoint(ctx)

        handler = registered["data_received"]

        # commit_turn creates the _commit_and_reply task (not yet started).
        handler(_data_packet(json.dumps({"type": "commit_turn"}).encode()))

        # interrupt_playback arrives before any await — cancels the pending task.
        handler(_data_packet(json.dumps({"type": "interrupt_playback"}).encode()))

        # Let the event loop run: the task starts, hits asyncio.sleep(0), receives
        # the cancellation, raises CancelledError, and exits cleanly.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    mock_session.interrupt.assert_called_once()
    # generate_reply must NOT have been called — the task was cancelled first.
    mock_session.generate_reply.assert_not_called()


@pytest.mark.asyncio
async def test_on_metrics_tts_observes_latency(configured_settings: None) -> None:
    """TTSMetrics event must observe tts_ttfb_voice and tts_synthesis_voice stages."""
    ctx, _ = _make_ctx()
    mock_agent = MagicMock()
    metrics_handler_ref: list = []

    mock_session = AsyncMock()

    def capture_on(event: str):
        def decorator(fn):
            if event == "metrics_collected":
                metrics_handler_ref.append(fn)
            return fn

        return decorator

    mock_session.on = MagicMock(side_effect=capture_on)

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
        patch("taskorbit.worker.get_metrics") as mock_get_metrics,
    ):
        mock_metrics = MagicMock()
        mock_get_metrics.return_value = mock_metrics
        await entrypoint(ctx)

        assert metrics_handler_ref, "_on_metrics not registered"
        ev = MagicMock()
        ev.metrics = _make_tts_metrics(ttfb=0.12, duration=1.5)
        metrics_handler_ref[0](ev)

    mock_metrics.pipeline_latency_seconds.labels.assert_any_call(stage="tts_ttfb")
    mock_metrics.pipeline_latency_seconds.labels.assert_any_call(stage="tts_synthesis")


@pytest.mark.asyncio
async def test_on_metrics_stt_observes_latency(configured_settings: None) -> None:
    """STTMetrics with duration > 0 must observe the stt_processing stage."""
    ctx, _ = _make_ctx()
    mock_agent = MagicMock()
    metrics_handler_ref: list = []

    mock_session = AsyncMock()

    def capture_on(event: str):
        def decorator(fn):
            if event == "metrics_collected":
                metrics_handler_ref.append(fn)
            return fn

        return decorator

    mock_session.on = MagicMock(side_effect=capture_on)

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
        patch("taskorbit.worker.get_metrics") as mock_get_metrics,
    ):
        mock_metrics = MagicMock()
        mock_get_metrics.return_value = mock_metrics
        await entrypoint(ctx)

        ev = MagicMock()
        ev.metrics = _make_stt_metrics(duration=0.25)
        metrics_handler_ref[0](ev)

    mock_metrics.pipeline_latency_seconds.labels.assert_any_call(stage="stt_processing")


@pytest.mark.asyncio
async def test_on_metrics_stt_zero_duration_not_observed(configured_settings: None) -> None:
    """STTMetrics with duration == 0 must not call observe (avoids polluting histogram)."""
    ctx, _ = _make_ctx()
    mock_agent = MagicMock()
    metrics_handler_ref: list = []

    mock_session = AsyncMock()

    def capture_on(event: str):
        def decorator(fn):
            if event == "metrics_collected":
                metrics_handler_ref.append(fn)
            return fn

        return decorator

    mock_session.on = MagicMock(side_effect=capture_on)

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
        patch("taskorbit.worker.get_metrics") as mock_get_metrics,
    ):
        mock_metrics = MagicMock()
        mock_get_metrics.return_value = mock_metrics
        await entrypoint(ctx)

        ev = MagicMock()
        ev.metrics = _make_stt_metrics(duration=0.0)
        metrics_handler_ref[0](ev)

    # pipeline_latency_seconds must not have been called with stt_processing
    stt_calls = [
        c
        for c in mock_metrics.pipeline_latency_seconds.labels.call_args_list
        if c == ((), {"stage": "stt_processing"})
    ]
    assert not stt_calls


@pytest.mark.asyncio
async def test_local_participant_packet_ignored(configured_settings: None) -> None:
    """A packet whose sender identity matches the local participant must be ignored."""
    ctx, registered = _make_ctx()
    mock_session = _make_session_mock()
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
    ):
        await entrypoint(ctx)

    handler = registered["data_received"]
    local_identity = ctx.room.local_participant.identity
    packet = _data_packet(json.dumps({"type": "commit_turn"}).encode(), local_identity)
    handler(packet)

    mock_agent.request_reply.assert_not_called()


@pytest.mark.asyncio
async def test_interrupt_during_flush_delay_cancels_task(configured_settings: None) -> None:
    """interrupt_playback arriving while _commit_and_reply is sleeping on the
    Deepgram flush delay must cancel the task before generate_reply is called."""
    ctx, registered = _make_ctx()
    mock_session = _make_session_mock()
    mock_session.generate_reply = MagicMock(return_value=None)
    mock_session.interrupt = MagicMock()
    mock_agent = MagicMock()

    small_delay = 0.01

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
        patch("taskorbit.worker._DEEPGRAM_FLUSH_DELAY_S", small_delay),
    ):
        await entrypoint(ctx)

        handler = registered["data_received"]

        # Start the commit/reply cycle — task enters asyncio.sleep(small_delay).
        handler(_data_packet(json.dumps({"type": "commit_turn"}).encode()))
        await asyncio.sleep(0)  # let the task start and reach the sleep

        # Interrupt arrives while the task is still sleeping.
        handler(_data_packet(json.dumps({"type": "interrupt_playback"}).encode()))

        # Allow the event loop to process the cancellation.
        await asyncio.sleep(small_delay * 2)

    mock_session.interrupt.assert_called_once()
    mock_session.generate_reply.assert_not_called()


@pytest.mark.asyncio
async def test_interrupt_after_completed_task_does_not_raise(configured_settings: None) -> None:
    """interrupt_playback sent after the reply task already finished must still
    call session.interrupt() without raising an error (reply_task.done() guard)."""
    ctx, registered = _make_ctx()
    mock_session = _make_session_mock()
    mock_session.generate_reply = MagicMock(return_value=None)
    mock_session.interrupt = MagicMock()
    mock_agent = MagicMock()

    with (
        patch("taskorbit.worker.build_agent_session", return_value=mock_session),
        patch("taskorbit.worker.build_default_agent", return_value=mock_agent),
        patch("taskorbit.worker._DEEPGRAM_FLUSH_DELAY_S", 0),
    ):
        await entrypoint(ctx)

        handler = registered["data_received"]

        # Let commit_turn run to completion first.
        handler(_data_packet(json.dumps({"type": "commit_turn"}).encode()))
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        mock_session.generate_reply.assert_called_once()

        # Now interrupt arrives — reply_task is already done, should not raise.
        handler(_data_packet(json.dumps({"type": "interrupt_playback"}).encode()))

    mock_session.interrupt.assert_called_once()
