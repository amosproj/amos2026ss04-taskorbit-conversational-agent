"""Tests for the STT/TTS provider-dispatch factory in ``build_agent_session`` (#135).

Covers the full 2x2 provider matrix (deepgram/elevenlabs for either stage,
independently), the voice_id precedence fix (agent config wins over env),
and the cross-provider model fallbacks. All plugin constructors are mocked;
no live API is touched.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from taskorbit.config import get_settings
from taskorbit.livekit_agent.session import (
    _is_deepgram_stt_model,
    _is_deepgram_tts_model,
    _is_elevenlabs_stt_model,
    _is_elevenlabs_tts_model,
    _resolve_model,
    build_agent_session,
)
from taskorbit.types import AgentConfig, STTConfig, TTSConfig

_ENV_DEEPGRAM_MODEL = "nova-3"
_ENV_ELEVENLABS_MODEL = "eleven_multilingual_v2"
_ENV_VOICE_ID = "env-voice-id"


@pytest.fixture
def provider_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Complete env for both vendors so ``get_settings()`` resolves."""
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-key")
    monkeypatch.setenv("DEEPGRAM_MODEL", _ENV_DEEPGRAM_MODEL)
    monkeypatch.setenv("DEEPGRAM_LANGUAGE", "multi")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", _ENV_VOICE_ID)
    monkeypatch.setenv("ELEVENLABS_MODEL", _ENV_ELEVENLABS_MODEL)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _agent_config(stt: STTConfig, tts: TTSConfig) -> AgentConfig:
    return AgentConfig(
        id="agent-1",
        name="Matrix Bot",
        persona="p",
        greeting="hi",
        stt=stt,
        tts=tts,
    )


def _build_with_config(config: AgentConfig | None) -> dict[str, MagicMock]:
    """Run ``build_agent_session`` with every plugin constructor mocked.

    The module ``logger`` is patched too so tests can assert that a
    cross-provider model mismatch logs the ``model_not_valid_for_provider``
    warning, which is the only production signal of a misconfigured agent.
    """
    with (
        patch("taskorbit.livekit_agent.session.silero.VAD"),
        patch("taskorbit.livekit_agent.session.deepgram.STT") as dg_stt,
        patch("taskorbit.livekit_agent.session.deepgram.TTS") as dg_tts,
        patch("taskorbit.livekit_agent.session.elevenlabs.STT") as el_stt,
        patch("taskorbit.livekit_agent.session.elevenlabs.TTS") as el_tts,
        patch("taskorbit.livekit_agent.session.AgentSession") as session,
        patch("taskorbit.livekit_agent.session.logger") as logger,
    ):
        build_agent_session(agent_config=config)
    return {
        "deepgram_stt": dg_stt,
        "deepgram_tts": dg_tts,
        "elevenlabs_stt": el_stt,
        "elevenlabs_tts": el_tts,
        "session": session,
        "logger": logger,
    }


def _model_warnings(logger: MagicMock) -> list[dict]:
    """Return the kwargs of every ``model_not_valid_for_provider`` warning."""
    return [
        call.kwargs
        for call in logger.warning.call_args_list
        if call.args and call.args[0] == "model_not_valid_for_provider"
    ]


def _assert_model_warning(logger: MagicMock, *, stage: str, provider: str) -> None:
    """Assert the misconfiguration warning fired for this stage/provider."""
    warnings = _model_warnings(logger)
    assert warnings, "expected a model_not_valid_for_provider warning, none logged"
    assert any(
        w.get("stage") == stage and w.get("provider") == provider for w in warnings
    ), f"expected warning for stage={stage} provider={provider}, got {warnings}"


# ---------------------------------------------------------------------------
# The 2x2 provider matrix (AC1 + AC2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stt_provider", "stt_model", "tts_provider", "tts_model", "want_stt", "want_tts"),
    [
        (
            "deepgram",
            "nova-3",
            "elevenlabs",
            "eleven_multilingual_v2",
            "deepgram_stt",
            "elevenlabs_tts",
        ),
        ("deepgram", "nova-3", "deepgram", "aura-2-andromeda-en", "deepgram_stt", "deepgram_tts"),
        (
            "elevenlabs",
            "scribe_v2_realtime",
            "elevenlabs",
            "eleven_multilingual_v2",
            "elevenlabs_stt",
            "elevenlabs_tts",
        ),
        (
            "elevenlabs",
            "scribe_v2_realtime",
            "deepgram",
            "aura-2-andromeda-en",
            "elevenlabs_stt",
            "deepgram_tts",
        ),
    ],
)
def test_provider_matrix_constructs_correct_plugins(
    provider_settings: None,
    stt_provider: str,
    stt_model: str,
    tts_provider: str,
    tts_model: str,
    want_stt: str,
    want_tts: str,
) -> None:
    """Each matrix cell constructs exactly the selected plugin pair and wires
    the instances into the AgentSession."""
    config = _agent_config(
        stt=STTConfig.model_validate(
            {"provider": stt_provider, "language": "multi", "model": stt_model}
        ),
        tts=TTSConfig.model_validate(
            {"provider": tts_provider, "voice_id": "v-1", "model": tts_model}
        ),
    )
    mocks = _build_with_config(config)

    stt_mocks = {"deepgram_stt", "elevenlabs_stt"}
    tts_mocks = {"deepgram_tts", "elevenlabs_tts"}
    mocks[want_stt].assert_called_once()
    mocks[want_tts].assert_called_once()
    for unused in (stt_mocks - {want_stt}) | (tts_mocks - {want_tts}):
        mocks[unused].assert_not_called()

    session_kwargs = mocks["session"].call_args.kwargs
    assert session_kwargs["stt"] is mocks[want_stt].return_value
    assert session_kwargs["tts"] is mocks[want_tts].return_value


# ---------------------------------------------------------------------------
# ElevenLabs STT model pinning (streaming-compatible models only)
# ---------------------------------------------------------------------------


def test_elevenlabs_stt_realtime_model_passes_through(provider_settings: None) -> None:
    config = _agent_config(
        stt=STTConfig.model_validate(
            {"provider": "elevenlabs", "language": "multi", "model": "scribe_v2_realtime"}
        ),
        tts=TTSConfig(),
    )
    mocks = _build_with_config(config)
    kwargs = mocks["elevenlabs_stt"].call_args.kwargs
    assert kwargs["model_id"] == "scribe_v2_realtime"
    assert kwargs["api_key"] == "el-key"
    # A valid model must stay silent, so the warning assertions elsewhere
    # are meaningful and not vacuously true.
    assert not _model_warnings(mocks["logger"])


@pytest.mark.parametrize("bad_model", ["scribe_v1", "scribe_v2", "nova-3", "whisper-large"])
def test_elevenlabs_stt_incompatible_model_falls_back_to_realtime(
    provider_settings: None, bad_model: str
) -> None:
    """Batch scribe models and cross-provider names both fall back: only
    scribe_v2_realtime streams, which the worker's turn handling requires."""
    config = _agent_config(
        stt=STTConfig.model_validate(
            {"provider": "elevenlabs", "language": "multi", "model": bad_model}
        ),
        tts=TTSConfig(),
    )
    mocks = _build_with_config(config)
    assert mocks["elevenlabs_stt"].call_args.kwargs["model_id"] == "scribe_v2_realtime"
    _assert_model_warning(mocks["logger"], stage="stt", provider="elevenlabs")


# ---------------------------------------------------------------------------
# Deepgram STT model sourcing
# ---------------------------------------------------------------------------


def test_deepgram_stt_model_from_config_overrides_env(provider_settings: None) -> None:
    config = _agent_config(
        stt=STTConfig.model_validate(
            {"provider": "deepgram", "language": "multi", "model": "nova-2"}
        ),
        tts=TTSConfig(),
    )
    mocks = _build_with_config(config)
    assert mocks["deepgram_stt"].call_args.kwargs["model"] == "nova-2"
    assert not _model_warnings(mocks["logger"])


def test_deepgram_stt_scribe_model_keeps_env_model(provider_settings: None) -> None:
    """A scribe model name on the deepgram provider is cross-provider garbage;
    keep the env-configured Deepgram model instead."""
    config = _agent_config(
        stt=STTConfig.model_validate(
            {"provider": "deepgram", "language": "multi", "model": "scribe_v1"}
        ),
        tts=TTSConfig(),
    )
    mocks = _build_with_config(config)
    assert mocks["deepgram_stt"].call_args.kwargs["model"] == _ENV_DEEPGRAM_MODEL
    _assert_model_warning(mocks["logger"], stage="stt", provider="deepgram")


def test_deepgram_stt_no_config_uses_env_defaults(provider_settings: None) -> None:
    """Without an agent config the historical env-driven construction applies."""
    mocks = _build_with_config(None)
    mocks["deepgram_stt"].assert_called_once_with(
        api_key="dg-key",
        model=_ENV_DEEPGRAM_MODEL,
        language="multi",
        smart_format=True,
        numerals=True,
        endpointing_ms=400,
    )
    mocks["elevenlabs_stt"].assert_not_called()
    mocks["deepgram_tts"].assert_not_called()


# ---------------------------------------------------------------------------
# Deepgram TTS branch
# ---------------------------------------------------------------------------


def test_deepgram_tts_ignores_voice_id_and_pins_audio_format(provider_settings: None) -> None:
    """Aura voices live in the model name; voice_id must not be forwarded.
    Encoding and sample rate are pinned against plugin-default drift."""
    config = _agent_config(
        stt=STTConfig(),
        tts=TTSConfig.model_validate(
            {"provider": "deepgram", "voice_id": "el-style-voice", "model": "aura-2-thalia-en"}
        ),
    )
    mocks = _build_with_config(config)
    kwargs = mocks["deepgram_tts"].call_args.kwargs
    assert kwargs["model"] == "aura-2-thalia-en"
    assert "voice_id" not in kwargs
    assert kwargs["encoding"] == "linear16"
    assert kwargs["sample_rate"] == 24000


def test_deepgram_tts_cross_provider_model_falls_back(provider_settings: None) -> None:
    config = _agent_config(
        stt=STTConfig(),
        tts=TTSConfig.model_validate(
            {"provider": "deepgram", "voice_id": "v", "model": "eleven_multilingual_v2"}
        ),
    )
    mocks = _build_with_config(config)
    assert mocks["deepgram_tts"].call_args.kwargs["model"] == "aura-2-andromeda-en"
    _assert_model_warning(mocks["logger"], stage="tts", provider="deepgram")


# ---------------------------------------------------------------------------
# voice_id precedence (the placeholder bug fix)
# ---------------------------------------------------------------------------


def test_voice_id_config_wins_over_env(provider_settings: None) -> None:
    """The agent config's voice_id takes precedence over ELEVENLABS_VOICE_ID.
    Previously env always won, making the config field a placebo."""
    config = _agent_config(
        stt=STTConfig(),
        tts=TTSConfig.model_validate(
            {
                "provider": "elevenlabs",
                "voice_id": "config-voice-id",
                "model": "eleven_multilingual_v2",
            }
        ),
    )
    mocks = _build_with_config(config)
    assert mocks["elevenlabs_tts"].call_args.kwargs["voice_id"] == "config-voice-id"


def test_voice_id_empty_config_falls_back_to_env(provider_settings: None) -> None:
    config = _agent_config(
        stt=STTConfig(),
        tts=TTSConfig.model_validate(
            {"provider": "elevenlabs", "voice_id": "", "model": "eleven_multilingual_v2"}
        ),
    )
    mocks = _build_with_config(config)
    assert mocks["elevenlabs_tts"].call_args.kwargs["voice_id"] == _ENV_VOICE_ID


def test_voice_id_no_config_uses_env(provider_settings: None) -> None:
    mocks = _build_with_config(None)
    assert mocks["elevenlabs_tts"].call_args.kwargs["voice_id"] == _ENV_VOICE_ID


# ---------------------------------------------------------------------------
# ElevenLabs TTS model sourcing
# ---------------------------------------------------------------------------


def test_elevenlabs_tts_model_from_config_overrides_env(provider_settings: None) -> None:
    config = _agent_config(
        stt=STTConfig(),
        tts=TTSConfig.model_validate(
            {"provider": "elevenlabs", "voice_id": "v", "model": "eleven_turbo_v2_5"}
        ),
    )
    mocks = _build_with_config(config)
    assert mocks["elevenlabs_tts"].call_args.kwargs["model"] == "eleven_turbo_v2_5"


def test_elevenlabs_tts_cross_provider_model_keeps_env_model(provider_settings: None) -> None:
    config = _agent_config(
        stt=STTConfig(),
        tts=TTSConfig.model_validate(
            {"provider": "elevenlabs", "voice_id": "v", "model": "aura-2-thalia-en"}
        ),
    )
    mocks = _build_with_config(config)
    assert mocks["elevenlabs_tts"].call_args.kwargs["model"] == _ENV_ELEVENLABS_MODEL
    _assert_model_warning(mocks["logger"], stage="tts", provider="elevenlabs")


# ---------------------------------------------------------------------------
# Unified cross-provider detection (PR #141 review: closes the Deepgram-STT
# silent-fallthrough and proves all four branches detect consistently)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unknown_model", ["scribe_v2_realtime", "eleven_multilingual_v2", "nova3", "garbage-model"]
)
def test_deepgram_stt_unknown_model_falls_back_and_warns(
    provider_settings: None, unknown_model: str
) -> None:
    """A model that is not a Deepgram Nova model must NOT be passed verbatim to
    the Deepgram API (where it would fail silently mid-call). Before the shared
    detection helper, the Deepgram STT branch only rejected ``scribe_`` names,
    so these strings slipped through. Now they fall back to env + warn."""
    config = _agent_config(
        stt=STTConfig.model_validate(
            {"provider": "deepgram", "language": "multi", "model": unknown_model}
        ),
        tts=TTSConfig(),
    )
    mocks = _build_with_config(config)
    assert mocks["deepgram_stt"].call_args.kwargs["model"] == _ENV_DEEPGRAM_MODEL
    _assert_model_warning(mocks["logger"], stage="stt", provider="deepgram")


def test_provider_predicates() -> None:
    """The four per-provider model predicates only accept their own models."""
    assert _is_deepgram_stt_model("nova-3")
    assert _is_deepgram_stt_model("nova-2")
    assert not _is_deepgram_stt_model("scribe_v2_realtime")
    assert not _is_deepgram_stt_model("whisper-large")
    assert not _is_deepgram_stt_model("nova3")  # typo: missing hyphen

    assert _is_elevenlabs_stt_model("scribe_v2_realtime")
    assert not _is_elevenlabs_stt_model("scribe_v1")
    assert not _is_elevenlabs_stt_model("nova-3")

    assert _is_deepgram_tts_model("aura-2-andromeda-en")
    assert not _is_deepgram_tts_model("eleven_multilingual_v2")

    assert _is_elevenlabs_tts_model("eleven_turbo_v2_5")
    assert not _is_elevenlabs_tts_model("aura-2-andromeda-en")


def test_resolve_model_valid_passes_through_without_warning() -> None:
    with patch("taskorbit.livekit_agent.session.logger") as logger:
        result = _resolve_model(
            stage="stt",
            provider="deepgram",
            configured="nova-3",
            is_valid=_is_deepgram_stt_model,
            fallback="fallback-model",
        )
    assert result == "nova-3"
    logger.warning.assert_not_called()


def test_resolve_model_invalid_falls_back_and_warns() -> None:
    with patch("taskorbit.livekit_agent.session.logger") as logger:
        result = _resolve_model(
            stage="tts",
            provider="elevenlabs",
            configured="aura-2-andromeda-en",
            is_valid=_is_elevenlabs_tts_model,
            fallback="eleven_multilingual_v2",
        )
    assert result == "eleven_multilingual_v2"
    logger.warning.assert_called_once()
    assert logger.warning.call_args.args[0] == "model_not_valid_for_provider"
    assert logger.warning.call_args.kwargs["configured_model"] == "aura-2-andromeda-en"


def test_resolve_model_empty_config_falls_back_silently() -> None:
    """An empty/unset model is not a misconfiguration, just a deferral to the
    default, so it falls back WITHOUT a warning."""
    with patch("taskorbit.livekit_agent.session.logger") as logger:
        result = _resolve_model(
            stage="stt",
            provider="deepgram",
            configured="",
            is_valid=_is_deepgram_stt_model,
            fallback="nova-3",
        )
    assert result == "nova-3"
    logger.warning.assert_not_called()
