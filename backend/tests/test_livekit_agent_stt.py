"""Tests for Deepgram STT wiring in ``build_agent_session``.

The legacy ``TaskOrbitVoiceAgent._run_stt`` helpers were removed with the
in-repo worker; this module instead asserts that ``session.build_agent_session``
constructs ``livekit.plugins.deepgram.STT`` with credentials from
``Settings`` (environment).
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest

from taskorbit.config import get_settings
from taskorbit.livekit_agent.session import build_agent_session

_FAKE_API_KEY = "test-deepgram-key"
_FAKE_MODEL = "nova-3"
_FAKE_LANGUAGE = "multi"


@pytest.fixture
def stt_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Deepgram env vars + dummy ElevenLabs so ``get_settings()`` is complete."""
    monkeypatch.setenv("DEEPGRAM_API_KEY", _FAKE_API_KEY)
    monkeypatch.setenv("DEEPGRAM_MODEL", _FAKE_MODEL)
    monkeypatch.setenv("DEEPGRAM_LANGUAGE", _FAKE_LANGUAGE)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "el-voice")
    monkeypatch.setenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_build_agent_session_deepgram_stt_uses_settings(
    stt_settings: None,
) -> None:
    """STT plugin is constructed with api_key, model, and language from config."""
    with (
        patch("taskorbit.livekit_agent.session.silero.VAD") as mock_vad,
        patch("taskorbit.livekit_agent.session.deepgram.STT") as mock_stt,
        patch("taskorbit.livekit_agent.session.elevenlabs.TTS") as mock_tts,
        patch("taskorbit.livekit_agent.session.AgentSession") as mock_session,
    ):
        build_agent_session()

    mock_stt.assert_called_once_with(
        api_key=_FAKE_API_KEY,
        model=_FAKE_MODEL,
        language=_FAKE_LANGUAGE,
    )
    kwargs = mock_session.call_args.kwargs
    assert kwargs["stt"] is mock_stt.return_value
    assert mock_vad.load.called
    assert mock_tts.called


def test_build_agent_session_deepgram_stt_respects_custom_language(
    stt_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPGRAM_LANGUAGE", "de")
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

    mock_stt.assert_called_once_with(
        api_key=_FAKE_API_KEY,
        model=_FAKE_MODEL,
        language="de",
    )
    assert mock_vad.load.called
    assert mock_tts.called
