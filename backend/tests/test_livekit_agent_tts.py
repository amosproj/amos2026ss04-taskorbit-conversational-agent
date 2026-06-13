"""Tests for ElevenLabs TTS wiring in ``build_agent_session``.

The legacy ``TaskOrbitVoiceAgent._run_tts`` stream helpers were removed with
the in-repo worker; this module asserts that ``session.build_agent_session``
constructs ``livekit.plugins.elevenlabs.TTS`` with credentials from
``Settings`` (environment).
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from livekit.plugins.elevenlabs import VoiceSettings

from taskorbit.config import get_settings
from taskorbit.livekit_agent.session import build_agent_session

_FAKE_API_KEY = "test-elevenlabs-key"
_FAKE_VOICE_ID = "test-voice-id"
_FAKE_MODEL = "eleven_multilingual_v2"


@pytest.fixture
def tts_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """ElevenLabs env vars + dummy Deepgram so ``get_settings()`` is complete."""
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-key")
    monkeypatch.setenv("DEEPGRAM_MODEL", "nova-3")
    monkeypatch.setenv("DEEPGRAM_LANGUAGE", "multi")
    monkeypatch.setenv("ELEVENLABS_API_KEY", _FAKE_API_KEY)
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", _FAKE_VOICE_ID)
    monkeypatch.setenv("ELEVENLABS_MODEL", _FAKE_MODEL)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_build_agent_session_elevenlabs_tts_uses_settings(
    tts_settings: None,
) -> None:
    """TTS plugin is constructed with api_key, voice_id, and model from config."""
    with (
        patch("taskorbit.livekit_agent.session.silero.VAD") as mock_vad,
        patch("taskorbit.livekit_agent.session.deepgram.STT") as mock_stt,
        patch("taskorbit.livekit_agent.session.elevenlabs.TTS") as mock_tts,
        patch("taskorbit.livekit_agent.session.AgentSession") as mock_session,
    ):
        build_agent_session()

    mock_tts.assert_called_once()
    tts_kwargs = mock_tts.call_args.kwargs
    assert tts_kwargs["api_key"] == _FAKE_API_KEY
    assert tts_kwargs["voice_id"] == _FAKE_VOICE_ID
    assert tts_kwargs["model"] == _FAKE_MODEL
    assert tts_kwargs["voice_settings"] == VoiceSettings(
        stability=0.75, similarity_boost=0.75, style=0.0, speed=1.0, use_speaker_boost=True
    )
    kwargs = mock_session.call_args.kwargs
    assert kwargs["tts"] is mock_tts.return_value
    assert mock_vad.load.called
    assert mock_stt.called


def test_build_agent_session_elevenlabs_tts_respects_custom_voice(
    tts_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "custom-voice-123")
    get_settings.cache_clear()
    try:
        with (
            patch("taskorbit.livekit_agent.session.silero.VAD") as mock_vad,
            patch("taskorbit.livekit_agent.session.deepgram.STT") as mock_stt,
            patch("taskorbit.livekit_agent.session.elevenlabs.TTS") as mock_tts,
            patch("taskorbit.livekit_agent.session.AgentSession"),
        ):
            build_agent_session()
    finally:
        get_settings.cache_clear()

    mock_tts.assert_called_once()
    tts_kwargs = mock_tts.call_args.kwargs
    assert tts_kwargs["api_key"] == _FAKE_API_KEY
    assert tts_kwargs["voice_id"] == "custom-voice-123"
    assert tts_kwargs["model"] == _FAKE_MODEL
    assert mock_vad.load.called
    assert mock_stt.called


def test_build_agent_session_respects_agent_config_override(
    tts_settings: None,
) -> None:
    """agent_config.tts.voice_id should override global env settings (#100)."""
    from taskorbit.types import AgentConfig, TTSConfig

    cfg = AgentConfig(
        id="overrider",
        name="Overrider",
        persona="test",
        greeting="test",
        tts=TTSConfig(voice_id="override-voice-id", model="override-model"),
    )

    with (
        patch("taskorbit.livekit_agent.session.silero.VAD"),
        patch("taskorbit.livekit_agent.session.deepgram.STT"),
        patch("taskorbit.livekit_agent.session.elevenlabs.TTS") as mock_tts,
        patch("taskorbit.livekit_agent.session.AgentSession"),
    ):
        build_agent_session(agent_config=cfg)

    mock_tts.assert_called_once()
    tts_kwargs = mock_tts.call_args.kwargs
    assert tts_kwargs["voice_id"] == "override-voice-id"
    assert tts_kwargs["model"] == "override-model"
