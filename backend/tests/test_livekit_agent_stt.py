"""Tests for TaskOrbitVoiceAgent._run_stt (Deepgram STT pipeline).

Scenarios covered:

1. Transcript text is streamed from Deepgram and yielded to the caller.
2. STT is initialised with the correct api_key/model/language from settings.
3. aclose() is always called on the STT stream, even when transcription fails.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.config import get_settings
from taskorbit.livekit_agent import TaskOrbitVoiceAgent
from taskorbit.orchestration import ConversationOrchestrator

_FAKE_API_KEY = "test-deepgram-key"
_FAKE_MODEL = "nova-3"
_FAKE_LANGUAGE = "multi"
_FAKE_TRANSCRIPT = "Hello world"
_FAKE_AUDIO_CHUNK = b"\x00" * 320  # 160 samples × 2 bytes (16-bit PCM)


@pytest.fixture
def configured_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Inject Deepgram credentials into the cached Settings instance."""
    monkeypatch.setenv("DEEPGRAM_API_KEY", _FAKE_API_KEY)
    monkeypatch.setenv("DEEPGRAM_MODEL", _FAKE_MODEL)
    monkeypatch.setenv("DEEPGRAM_LANGUAGE", _FAKE_LANGUAGE)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _make_agent() -> TaskOrbitVoiceAgent:
    return TaskOrbitVoiceAgent(orchestrator=ConversationOrchestrator())


async def _audio_chunks() -> AsyncIterator[bytes]:
    yield _FAKE_AUDIO_CHUNK


async def _failing_audio() -> AsyncIterator[bytes]:
    raise RuntimeError("Deepgram unreachable")
    yield b""  # make it an async generator


def _make_stt_stream(transcript: str, event_type: object) -> MagicMock:
    """Return a mock SpeechStream that yields one FINAL_TRANSCRIPT event."""
    fake_alternative = MagicMock()
    fake_alternative.text = transcript

    fake_event = MagicMock()
    fake_event.type = event_type
    fake_event.alternatives = [fake_alternative]

    async def _event_iter() -> AsyncIterator[MagicMock]:
        yield fake_event

    stream = MagicMock()
    stream.push_frame = MagicMock()
    stream.aclose = AsyncMock()
    stream.__aiter__ = lambda self: _event_iter().__aiter__()
    return stream


@pytest.mark.asyncio
async def test_run_stt_yields_transcript_from_deepgram(
    configured_settings: None,
) -> None:
    with (
        patch("taskorbit.livekit_agent.lk_stt.SpeechEventType") as mock_event_type,
        patch("taskorbit.livekit_agent.rtc.AudioFrame"),
        patch("taskorbit.livekit_agent.deepgram.STT") as mock_stt_cls,
    ):
        stream = _make_stt_stream(_FAKE_TRANSCRIPT, mock_event_type.FINAL_TRANSCRIPT)
        mock_stt_cls.return_value.stream.return_value = stream

        transcripts = [t async for t in _make_agent()._run_stt(_audio_chunks())]

    assert transcripts == [_FAKE_TRANSCRIPT]


@pytest.mark.asyncio
async def test_run_stt_initialises_deepgram_with_settings(
    configured_settings: None,
) -> None:
    with (
        patch("taskorbit.livekit_agent.lk_stt.SpeechEventType") as mock_event_type,
        patch("taskorbit.livekit_agent.rtc.AudioFrame"),
        patch("taskorbit.livekit_agent.deepgram.STT") as mock_stt_cls,
    ):
        stream = _make_stt_stream(_FAKE_TRANSCRIPT, mock_event_type.FINAL_TRANSCRIPT)
        mock_stt_cls.return_value.stream.return_value = stream

        async for _ in _make_agent()._run_stt(_audio_chunks()):
            pass

    mock_stt_cls.assert_called_once_with(
        api_key=_FAKE_API_KEY,
        model=_FAKE_MODEL,
        language=_FAKE_LANGUAGE,
    )


@pytest.mark.asyncio
async def test_run_stt_closes_stream_on_error(
    configured_settings: None,
) -> None:
    with (
        patch("taskorbit.livekit_agent.rtc.AudioFrame"),
        patch("taskorbit.livekit_agent.deepgram.STT") as mock_stt_cls,
    ):
        stream = MagicMock()
        stream.push_frame = MagicMock()
        stream.aclose = AsyncMock()
        mock_stt_cls.return_value.stream.return_value = stream

        with pytest.raises(RuntimeError, match="Deepgram unreachable"):
            async for _ in _make_agent()._run_stt(_failing_audio()):
                pass

    stream.aclose.assert_awaited_once()
