"""Tests for TaskOrbitVoiceAgent._run_tts (ElevenLabs TTS pipeline).

Scenarios covered:

1. Audio bytes are streamed from ElevenLabs and yielded to the caller.
2. TTS is initialised with the correct voice/model/API-key from settings.
3. aclose() is always called on the TTS instance, even when synthesis fails.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.config import get_settings
from taskorbit.livekit_agent import TaskOrbitVoiceAgent
from taskorbit.orchestration import ConversationOrchestrator

_FAKE_API_KEY = "test-elevenlabs-key"
_FAKE_VOICE_ID = "test-voice-id"
_FAKE_MODEL = "eleven_multilingual_v2"
_FAKE_AUDIO_BYTES = b"\x00\x01\x02\x03"


@pytest.fixture
def configured_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Inject ElevenLabs credentials into the cached Settings instance."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", _FAKE_API_KEY)
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", _FAKE_VOICE_ID)
    monkeypatch.setenv("ELEVENLABS_MODEL", _FAKE_MODEL)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _make_agent() -> TaskOrbitVoiceAgent:
    return TaskOrbitVoiceAgent(orchestrator=ConversationOrchestrator())


def _make_synthesize_stream(audio_bytes: bytes) -> MagicMock:
    """Return a mock ChunkedStream that yields one audio frame with the given bytes."""
    fake_frame = MagicMock()
    fake_frame.data = audio_bytes

    fake_audio = MagicMock()
    fake_audio.frame = fake_frame

    async def _audio_iter():
        yield fake_audio

    stream = MagicMock()
    stream.__aenter__ = AsyncMock(return_value=stream)
    stream.__aexit__ = AsyncMock(return_value=False)
    stream.__aiter__ = lambda self: _audio_iter().__aiter__()
    return stream


@pytest.mark.asyncio
async def test_run_tts_yields_audio_bytes_from_elevenlabs(
    configured_settings: None,
) -> None:
    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = _make_synthesize_stream(_FAKE_AUDIO_BYTES)
    mock_tts.aclose = AsyncMock()

    with patch("taskorbit.livekit_agent.elevenlabs.TTS", return_value=mock_tts):
        chunks = [chunk async for chunk in _make_agent()._run_tts("Hello world")]

    assert chunks == [_FAKE_AUDIO_BYTES]


@pytest.mark.asyncio
async def test_run_tts_initialises_elevenlabs_with_settings(
    configured_settings: None,
) -> None:
    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = _make_synthesize_stream(_FAKE_AUDIO_BYTES)
    mock_tts.aclose = AsyncMock()

    with patch("taskorbit.livekit_agent.elevenlabs.TTS", return_value=mock_tts) as mock_tts_cls:
        async for _ in _make_agent()._run_tts("Hello world"):
            pass

    mock_tts_cls.assert_called_once_with(
        voice_id=_FAKE_VOICE_ID,
        model=_FAKE_MODEL,
        api_key=_FAKE_API_KEY,
    )


@pytest.mark.asyncio
async def test_run_tts_closes_tts_instance_on_synthesis_error(
    configured_settings: None,
) -> None:
    failing_stream = MagicMock()
    failing_stream.__aenter__ = AsyncMock(side_effect=RuntimeError("ElevenLabs unreachable"))
    failing_stream.__aexit__ = AsyncMock(return_value=False)

    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = failing_stream
    mock_tts.aclose = AsyncMock()

    with patch("taskorbit.livekit_agent.elevenlabs.TTS", return_value=mock_tts):
        with pytest.raises(RuntimeError, match="ElevenLabs unreachable"):
            async for _ in _make_agent()._run_tts("Hello"):
                pass

    mock_tts.aclose.assert_awaited_once()
