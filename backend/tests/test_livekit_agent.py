"""Tests for the LiveKit `livekit_agent` session helpers (`build_agent_session`,

`OrchestratorAgent.llm_node`).

1. ``build_agent_session()`` constructs an AgentSession with the
   provider plugins reading the right settings.
2. ``OrchestratorAgent.llm_node`` translates a ChatContext into a
   ConversationRequest and yields the orchestrator's reply text.
3. ``OrchestratorAgent.llm_node`` yields nothing when the orchestrator
   returns an empty reply (defensive — keeps the TTS pipeline silent).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.config import get_settings
from taskorbit.livekit_agent.llm import OrchestratorAgent
from taskorbit.livekit_agent.session import build_agent_session
from taskorbit.types import (
    AgentConfig,
    ConversationResponse,
    Message,
    MessageRole,
)

_FAKE_DG_KEY = "test-deepgram-key"
_FAKE_DG_MODEL = "nova-3"
_FAKE_DG_LANG = "multi"
_FAKE_EL_KEY = "test-elevenlabs-key"
_FAKE_EL_VOICE = "test-voice-id"
_FAKE_EL_MODEL = "eleven_multilingual_v2"


@pytest.fixture
def configured_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DEEPGRAM_API_KEY", _FAKE_DG_KEY)
    monkeypatch.setenv("DEEPGRAM_MODEL", _FAKE_DG_MODEL)
    monkeypatch.setenv("DEEPGRAM_LANGUAGE", _FAKE_DG_LANG)
    monkeypatch.setenv("ELEVENLABS_API_KEY", _FAKE_EL_KEY)
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", _FAKE_EL_VOICE)
    monkeypatch.setenv("ELEVENLABS_MODEL", _FAKE_EL_MODEL)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_build_agent_session_uses_deepgram_elevenlabs_silero(
    configured_settings: None,
) -> None:
    """``build_agent_session`` wires plugins with credentials from settings."""
    with (
        patch("taskorbit.livekit_agent.session.silero.VAD") as mock_vad,
        patch("taskorbit.livekit_agent.session.deepgram.STT") as mock_stt,
        patch("taskorbit.livekit_agent.session.elevenlabs.TTS") as mock_tts,
        patch("taskorbit.livekit_agent.session.AgentSession") as mock_session,
    ):
        build_agent_session()

    mock_vad.load.assert_called_once_with(
        activation_threshold=0.7,
        deactivation_threshold=0.45,
        min_speech_duration=0.2,
        min_silence_duration=0.55,
        prefix_padding_duration=0.4,
    )
    mock_stt.assert_called_once_with(
        api_key=_FAKE_DG_KEY,
        model=_FAKE_DG_MODEL,
        language=_FAKE_DG_LANG,
    )
    mock_tts.assert_called_once()
    tts_kwargs = mock_tts.call_args.kwargs
    assert tts_kwargs["api_key"] == _FAKE_EL_KEY
    assert tts_kwargs["voice_id"] == _FAKE_EL_VOICE
    assert tts_kwargs["model"] == _FAKE_EL_MODEL
    mock_session.assert_called_once()
    kwargs = mock_session.call_args.kwargs
    assert kwargs["vad"] is mock_vad.load.return_value
    assert kwargs["stt"] is mock_stt.return_value
    assert kwargs["tts"] is mock_tts.return_value
    assert kwargs["turn_handling"]["endpointing"]["mode"] == "manual"
    # Barge-in is enabled; brief noises are ignored via the duration threshold.
    assert kwargs["allow_interruptions"] is True
    assert kwargs["min_interruption_duration"] == 0.8


def _make_chat_ctx(messages: list[tuple[str, str]]) -> Any:
    """Build a duck-typed ChatContext with the items the adapter reads."""
    items = []
    for role, content in messages:
        item = MagicMock()
        item.role = role
        item.content = content
        items.append(item)
    ctx = MagicMock()
    ctx.items = items
    return ctx


def _make_agent(reply: str) -> tuple[OrchestratorAgent, MagicMock]:
    orchestrator = MagicMock()
    orchestrator.process_message = AsyncMock(
        return_value=ConversationResponse(
            conversation_id="test-conv",
            reply=Message(role=MessageRole.ASSISTANT, content=reply),
        )
    )
    agent = OrchestratorAgent(
        orchestrator=orchestrator,
        agent_config=AgentConfig(
            id="agent-1",
            name="TestBot",
            persona="A test bot.",
            greeting="Hi!",
        ),
        conversation_id="test-conv",
    )
    return agent, orchestrator


@pytest.mark.asyncio
async def test_llm_node_yields_orchestrator_reply() -> None:
    agent, orchestrator = _make_agent("Hello back!")
    chat_ctx = _make_chat_ctx([("user", "Hello there")])

    agent.request_reply()
    chunks = [c async for c in agent.llm_node(chat_ctx, [], MagicMock())]

    assert chunks == ["Hello back!"]
    orchestrator.process_message.assert_awaited_once()
    request = orchestrator.process_message.await_args.args[0]
    assert [(m.role, m.content) for m in request.messages] == [
        (MessageRole.USER, "Hello there"),
    ]


@pytest.mark.asyncio
async def test_llm_node_skips_empty_reply() -> None:
    agent, _ = _make_agent("")
    chat_ctx = _make_chat_ctx([("user", "Hi")])

    chunks = [c async for c in agent.llm_node(chat_ctx, [], MagicMock())]

    assert chunks == []


@pytest.mark.asyncio
async def test_llm_node_filters_unsupported_chat_items() -> None:
    """Items with unrecognised roles or empty content are dropped silently."""
    agent, orchestrator = _make_agent("ack")
    chat_ctx = _make_chat_ctx(
        [
            ("user", "real message"),
            ("tool", "should be ignored"),
            ("assistant", ""),
        ]
    )

    agent.request_reply()
    [_ async for _ in agent.llm_node(chat_ctx, [], MagicMock())]

    request = orchestrator.process_message.await_args.args[0]
    assert [(m.role, m.content) for m in request.messages] == [
        (MessageRole.USER, "real message"),
    ]


# ---------------------------------------------------------------------------
# voice_turn_latency_seconds metric
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_node_records_voice_turn_latency() -> None:
    """voice_turn_latency_seconds is observed when request_reply(t_commit) is set."""
    import time

    agent, _ = _make_agent("reply")
    chat_ctx = _make_chat_ctx([("user", "hello")])
    mock_metrics = MagicMock()

    t_commit = time.perf_counter()
    agent.request_reply(t_commit=t_commit)

    with patch("taskorbit.livekit_agent.llm.get_metrics", return_value=mock_metrics):
        [_ async for _ in agent.llm_node(chat_ctx, [], MagicMock())]

    mock_metrics.voice_turn_latency_seconds.observe.assert_called_once()
    observed = mock_metrics.voice_turn_latency_seconds.observe.call_args.args[0]
    assert 0 <= observed < 5.0


@pytest.mark.asyncio
async def test_llm_node_skips_latency_when_no_commit_time() -> None:
    """voice_turn_latency_seconds is NOT observed when request_reply() has no t_commit set."""
    agent, _ = _make_agent("reply")
    chat_ctx = _make_chat_ctx([("user", "hello")])
    mock_metrics = MagicMock()

    # Manually set _t_commit to None to simulate no commit time
    agent._reply_requested = True
    agent._t_commit = None

    with patch("taskorbit.livekit_agent.llm.get_metrics", return_value=mock_metrics):
        [_ async for _ in agent.llm_node(chat_ctx, [], MagicMock())]

    mock_metrics.voice_turn_latency_seconds.observe.assert_not_called()


# ---------------------------------------------------------------------------
# Voice-path persona guardrails (ticket #69)
# ---------------------------------------------------------------------------


def test_default_agent_config_has_persona_guardrails() -> None:
    """The voice worker's fallback AgentConfig must carry persona_constraints,
    so the voice path receives the same guardrail injection as the text path
    until token-metadata wiring lands (separate ticket)."""
    from taskorbit.livekit_agent.llm import _default_agent_config

    config = _default_agent_config()
    assert config.persona_constraints is not None
    assert config.persona_constraints.scope is not None
    assert len(config.persona_constraints.out_of_scope) > 0
    assert config.persona_constraints.refusal_template is not None


@pytest.mark.asyncio
async def test_voice_path_propagates_persona_guardrails_into_prompt() -> None:
    """End-to-end voice path: the guardrail text reaches the LLM client.

    Mirrors test_persona_guardrails_flow_through_to_llm_prompt for the
    text path. Uses a real ConversationOrchestrator so _build_system_prompt
    fires, and asserts the augmented prompt includes the refusal_template
    line from _default_agent_config.
    """
    from taskorbit.config import Settings
    from taskorbit.livekit_agent.llm import _default_agent_config
    from taskorbit.orchestration import ConversationOrchestrator

    orchestrator = ConversationOrchestrator(
        settings=Settings(openai_api_key="sk-test", google_api_key="AIza-test")
    )
    voice_agent_config = _default_agent_config()
    refusal = voice_agent_config.persona_constraints.refusal_template

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="Sorry, only TechStore.")

    agent = OrchestratorAgent(
        orchestrator=orchestrator,
        agent_config=voice_agent_config,
        conversation_id="voice-conv",
    )
    chat_ctx = _make_chat_ctx([("user", "I'm just very sad.")])
    agent.request_reply()

    with patch("taskorbit.integrations.llm.factory.get_llm_client", return_value=mock_client):
        [_ async for _ in agent.llm_node(chat_ctx, [], MagicMock())]

    augmented_prompt = mock_client.generate.call_args.args[0]
    assert "Scope: " in augmented_prompt
    assert "Out of scope (politely redirect):" in augmented_prompt
    assert f'"{refusal}"' in augmented_prompt
