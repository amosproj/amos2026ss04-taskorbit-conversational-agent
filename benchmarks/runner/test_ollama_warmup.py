"""Tests for Ollama VRAM warmup (#68)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

_RUNNER_DIR = Path(__file__).parent
if str(_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNNER_DIR))

from component_config import OllamaWarmupSettings, PipelineComponentConfig
from ollama_warmup import effective_warmup_buffer_seconds, warmup_ollama_pipeline


def _ollama_pipeline() -> PipelineComponentConfig:
    return PipelineComponentConfig(
        name="oss-ollama-deepgram-deepgram",
        stt_provider="deepgram",
        stt_model="nova-2",
        llm_provider="ollama",
        llm_model="gemma4:26b",
        tts_provider="deepgram",
        tts_voice_id="aura-2-andromeda-en",
        tts_model="aura-2-andromeda-en",
    )


def test_ollama_warmup_settings_from_yaml() -> None:
    settings = OllamaWarmupSettings.from_yaml(
        {"enabled": True, "buffer_seconds": 45, "timeout_seconds": 120}
    )
    assert settings.enabled is True
    assert settings.buffer_seconds == 45
    assert settings.timeout_seconds == 120


def test_effective_warmup_buffer_env_override(monkeypatch) -> None:
    settings = OllamaWarmupSettings(buffer_seconds=30)
    monkeypatch.setenv("OLLAMA_WARMUP_BUFFER_SECONDS", "10")
    assert effective_warmup_buffer_seconds(settings) == 10.0


def test_warmup_skips_non_ollama_pipeline() -> None:
    cloud = PipelineComponentConfig(
        name="cloud",
        stt_provider="deepgram",
        stt_model="nova-3",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        tts_provider="elevenlabs",
        tts_voice_id="voice",
        tts_model="eleven_multilingual_v2",
    )
    result = asyncio.run(
        warmup_ollama_pipeline(
            api_url="http://localhost:8000",
            pipeline=cloud,
            headers={},
            settings=OllamaWarmupSettings(),
        )
    )
    assert result is None


def test_warmup_posts_primer_and_waits_buffer(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_WARMUP_BUFFER_SECONDS", "0")

    mock_response = httpx.Response(200, json={"reply": {"content": "Hi"}, "status": "success"})
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("ollama_warmup.httpx.AsyncClient", return_value=mock_client):
        elapsed = asyncio.run(
            warmup_ollama_pipeline(
                api_url="http://localhost:8000",
                pipeline=_ollama_pipeline(),
                headers={"Content-Type": "application/json"},
                settings=OllamaWarmupSettings(enabled=True, buffer_seconds=30),
            )
        )

    assert elapsed is not None
    mock_client.post.assert_awaited_once()
    call_kwargs = mock_client.post.await_args
    assert "/v1/conversations/process" in call_kwargs.args[0]
    payload = call_kwargs.kwargs["json"]
    assert payload["agent_config"]["llm"]["provider"] == "ollama"
    assert payload["messages"][0]["content"] == "Reply with one short word only."
