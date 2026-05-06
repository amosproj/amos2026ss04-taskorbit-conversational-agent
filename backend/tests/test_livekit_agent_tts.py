"""Tests for TaskOrbitVoiceAgent._run_tts."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.config import Settings
from taskorbit.livekit_agent import TaskOrbitVoiceAgent
from taskorbit.orchestration import ConversationOrchestrator


def _make_agent() -> TaskOrbitVoiceAgent:
    settings = Settings(
        elevenlabs_api_key="test-el-key",
        elevenlabs_voice_id="test-voice-id",
        elevenlabs_model="eleven_multilingual_v2",
    )
    return TaskOrbitVoiceAgent(orchestrator=ConversationOrchestrator(), settings=settings)


@pytest.mark.asyncio
async def test_run_tts_yields_audio_bytes() -> None:
    """_run_tts streams PCM bytes from ElevenLabs TTS for a given text."""
    fake_frame = MagicMock()
    fake_frame.data = b"\x00\x01\x02\x03"

    fake_audio = MagicMock()
    fake_audio.frame = fake_frame

    async def _async_audio_iter():
        yield fake_audio

    fake_stream = MagicMock()
    fake_stream.__aenter__ = AsyncMock(return_value=fake_stream)
    fake_stream.__aexit__ = AsyncMock(return_value=False)
    fake_stream.__aiter__ = lambda self: _async_audio_iter().__aiter__()

    mock_tts_instance = MagicMock()
    mock_tts_instance.synthesize = MagicMock(return_value=fake_stream)
    mock_tts_instance.aclose = AsyncMock()

    with patch("taskorbit.livekit_agent.elevenlabs.TTS", return_value=mock_tts_instance) as mock_tts_cls:
        agent = _make_agent()
        chunks = [chunk async for chunk in agent._run_tts("Hello world")]

    mock_tts_cls.assert_called_once_with(
        voice_id="test-voice-id",
        model="eleven_multilingual_v2",
        api_key="test-el-key",
    )
    assert chunks == [b"\x00\x01\x02\x03"]


@pytest.mark.asyncio
async def test_run_tts_closes_tts_on_error() -> None:
    """_run_tts calls aclose() even when synthesis raises."""
    fake_stream = AsyncMock()
    fake_stream.__aenter__ = AsyncMock(side_effect=RuntimeError("ElevenLabs error"))
    fake_stream.__aexit__ = AsyncMock(return_value=False)

    mock_tts_instance = MagicMock()
    mock_tts_instance.synthesize = MagicMock(return_value=fake_stream)
    mock_tts_instance.aclose = AsyncMock()

    with patch("taskorbit.livekit_agent.elevenlabs.TTS", return_value=mock_tts_instance):
        agent = _make_agent()
        with pytest.raises(RuntimeError, match="ElevenLabs error"):
            async for _ in agent._run_tts("Hello"):
                pass

    mock_tts_instance.aclose.assert_awaited_once()
