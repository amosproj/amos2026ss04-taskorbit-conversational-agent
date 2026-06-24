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
from taskorbit.livekit_agent.llm import OrchestratorAgent, _voice_confirmation_decision
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
        deactivation_threshold=0.6,
        min_speech_duration=0.2,
        min_silence_duration=1.5,
        prefix_padding_duration=0.4,
    )
    mock_stt.assert_called_once_with(
        api_key=_FAKE_DG_KEY,
        model=_FAKE_DG_MODEL,
        language=_FAKE_DG_LANG,
        smart_format=True,
        numerals=True,
        endpointing_ms=400,
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
    # Server-side VAD drives end-of-turn (#153); the prior endpointing.mode
    # "manual" was a no-op typo (mode only accepts "fixed"/"dynamic").
    assert kwargs["turn_handling"]["turn_detection"] == "vad"
    # Preemptive generation is disabled (#153): preemptive_tts=False does NOT
    # stop the framework's early llm_node call, so enabled=False is required to
    # keep the worker's commit-driven reply the single reply path.
    assert kwargs["turn_handling"]["preemptive_generation"]["enabled"] is False
    # Interruption is left at LiveKit 1.6.0 defaults: a more aggressive
    # min_duration tripped the interrupter on echo/ambient and cancelled the
    # agent's own replies, so no override is set here (#153).
    assert "interruption" not in kwargs["turn_handling"]


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


@pytest.fixture(autouse=True)
def _patch_async_session() -> Any:
    """Prevent llm_node tests from opening a real DB connection."""
    mock_db = AsyncMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    with patch("taskorbit.livekit_agent.llm.AsyncSessionLocal", return_value=mock_session):
        yield


def _make_agent(reply: str) -> tuple[OrchestratorAgent, MagicMock]:
    orchestrator = MagicMock()
    response = ConversationResponse(
        conversation_id="test-conv",
        reply=Message(role=MessageRole.ASSISTANT, content=reply),
    )
    captured: list[Any] = []

    async def _process_message_stream(request: Any, db: Any = None, user_id: Any = None):
        captured.append(request)
        yield response

    orchestrator.process_message_stream = _process_message_stream
    orchestrator._captured = captured
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
    assert len(orchestrator._captured) == 1
    request = orchestrator._captured[0]
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

    request = orchestrator._captured[0]
    assert [(m.role, m.content) for m in request.messages] == [
        (MessageRole.USER, "real message"),
    ]


@pytest.mark.asyncio
async def test_llm_node_dedups_repeated_same_user_input() -> None:
    """#153: a stale or duplicate trigger re-commits the same turn (no new user
    message in context). The orchestrator must answer a given turn once, not on
    every re-commit (which otherwise causes duplicate replies and
    concurrent-processing errors). Freshness is tracked by user-turn count, so a
    second trigger with no new turn is dropped.
    """
    agent, orchestrator = _make_agent("the one reply")
    chat_ctx = _make_chat_ctx([("user", "my order is damaged")])

    agent.request_reply()
    first = [c async for c in agent.llm_node(chat_ctx, [], MagicMock())]

    agent.request_reply()
    second = [c async for c in agent.llm_node(chat_ctx, [], MagicMock())]

    assert first == ["the one reply"]
    assert second == []
    assert len(orchestrator._captured) == 1


@pytest.mark.asyncio
async def test_llm_node_answers_each_new_turn_even_if_repeated() -> None:
    """#153 regression: a follow-up turn must get its own reply -- including when
    the user repeats the same words (e.g. re-confirming "yes"). The earlier
    content-only dedup wrongly dropped an identical follow-up; freshness is now
    by user-turn count so a genuinely new turn is always answered. This is the
    exact failure seen live, where a second utterance got no response.
    """
    agent, orchestrator = _make_agent("ok")

    agent.request_reply()
    first = [c async for c in agent.llm_node(_make_chat_ctx([("user", "yes")]), [], MagicMock())]

    # A new user turn arrives; the prior turn is still in context and the new
    # message repeats "yes". It must still be answered as a distinct turn.
    agent.request_reply()
    ctx2 = _make_chat_ctx([("user", "yes"), ("assistant", "ok"), ("user", "yes")])
    second = [c async for c in agent.llm_node(ctx2, [], MagicMock())]

    assert first == ["ok"]
    assert second == ["ok"]
    assert len(orchestrator._captured) == 2
    assert orchestrator._captured[1].messages[-1].content == "yes"


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

    # Arm the reply (no commit time) so llm_node runs but must skip the latency
    # metric because _t_commit is None.
    agent._reply_requested = True
    agent._t_commit = None

    with patch("taskorbit.livekit_agent.llm.get_metrics", return_value=mock_metrics):
        [_ async for _ in agent.llm_node(chat_ctx, [], MagicMock())]

    mock_metrics.voice_turn_latency_seconds.observe.assert_not_called()


# ---------------------------------------------------------------------------
# Voice-path persona guardrails
# ---------------------------------------------------------------------------

# Verification of the end-to-end voice path prompt generation.
# Assertions updated to match new imperative guardrail headers.


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
async def test_voice_path_propagates_persona_guardrails_into_prompt(
    mock_good_intent: object,
) -> None:
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

    # process_message_stream uses generate_stream for the main LLM call;
    # intent detection and slot extraction still go through generate.
    captured_stream_prompt: list[str] = []

    async def _generate_stream(prompt: str, messages: Any, config: Any):
        captured_stream_prompt.append(prompt)
        yield "Sorry, only TechStore."

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="")
    mock_client.generate_stream = _generate_stream

    agent = OrchestratorAgent(
        orchestrator=orchestrator,
        agent_config=voice_agent_config,
        conversation_id="voice-conv",
    )
    chat_ctx = _make_chat_ctx([("user", "I'm just very sad.")])
    agent.request_reply()

    with patch("taskorbit.integrations.llm.factory.get_llm_client", return_value=mock_client):
        [_ async for _ in agent.llm_node(chat_ctx, [], MagicMock())]

    assert captured_stream_prompt, "generate_stream was not called"
    augmented_prompt = captured_stream_prompt[0]
    # Asserting against the new imperative headers
    assert "Authorized Scope:" in augmented_prompt
    assert "CORE CONSTRAINT - Forbidden Topics" in augmented_prompt


# ---------------------------------------------------------------------------
# STT formatting: smart_format output flows through the pipeline unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_node_passes_formatted_number_unchanged() -> None:
    """Deepgram smart_format converts 'three two one' to '321' before it
    reaches the backend. The orchestrator must receive '321', not word form."""
    agent, orchestrator = _make_agent("Got it.")
    chat_ctx = _make_chat_ctx([("user", "my number is 321")])

    agent.request_reply()
    [_ async for _ in agent.llm_node(chat_ctx, [], MagicMock())]

    request = orchestrator._captured[0]
    assert request.messages[0].content == "my number is 321"


@pytest.mark.asyncio
async def test_llm_node_passes_email_from_smart_format_unchanged() -> None:
    """Deepgram smart_format emits 'user@example.com' — must reach the
    orchestrator intact so slot extraction can parse it as an email."""
    agent, orchestrator = _make_agent("Got it.")
    chat_ctx = _make_chat_ctx([("user", "my email is user@example.com")])

    agent.request_reply()
    [_ async for _ in agent.llm_node(chat_ctx, [], MagicMock())]

    request = orchestrator._captured[0]
    assert request.messages[0].content == "my email is user@example.com"


@pytest.mark.asyncio
async def test_llm_node_passes_date_from_smart_format_unchanged() -> None:
    """Deepgram smart_format converts spoken dates to '05/29/2026' — must
    arrive at the orchestrator in that formatted form."""
    agent, orchestrator = _make_agent("Got it.")
    chat_ctx = _make_chat_ctx([("user", "I need it by 05/29/2026")])

    agent.request_reply()
    [_ async for _ in agent.llm_node(chat_ctx, [], MagicMock())]

    request = orchestrator._captured[0]
    assert request.messages[0].content == "I need it by 05/29/2026"


@pytest.mark.asyncio
async def test_llm_node_normalizes_unicode_em_dash_from_stt() -> None:
    """Deepgram can emit an em dash (—) mid-utterance. It must be replaced
    with an ASCII hyphen before reaching the orchestrator to prevent
    UnicodeEncodeError in downstream LLM HTTP clients."""
    agent, orchestrator = _make_agent("Got it.")
    chat_ctx = _make_chat_ctx([("user", "tomorrow—maybe Thursday")])

    agent.request_reply()
    [_ async for _ in agent.llm_node(chat_ctx, [], MagicMock())]

    request = orchestrator._captured[0]
    assert "—" not in request.messages[0].content
    assert "-" in request.messages[0].content


def test_voice_confirmation_does_not_match_ok_substring_in_hello() -> None:
    assert _voice_confirmation_decision("hello") is None


def test_voice_confirmation_matches_explicit_confirm_and_reject() -> None:
    assert _voice_confirmation_decision("ok") == "confirm"
    assert _voice_confirmation_decision("Yes, proceed") == "confirm"
    assert _voice_confirmation_decision("go ahead please") == "confirm"
    assert _voice_confirmation_decision("cancel") == "reject"


# ---------------------------------------------------------------------------
# VAD silence threshold — regression guard for issue #102
# ---------------------------------------------------------------------------


def test_vad_silence_duration_prevents_premature_bubble_splits(
    configured_settings: None,
) -> None:
    """Regression guard: min_silence_duration must stay >= 1.5s.

    Lowering this threshold was the root cause of issue #102 — mid-utterance
    pauses caused Silero VAD to cut the segment early, splitting one utterance
    into multiple transcript bubbles. This test will fail if someone reduces
    the threshold without understanding the consequence.
    """
    with (
        patch("taskorbit.livekit_agent.session.silero.VAD") as mock_vad,
        patch("taskorbit.livekit_agent.session.deepgram.STT"),
        patch("taskorbit.livekit_agent.session.elevenlabs.TTS"),
        patch("taskorbit.livekit_agent.session.AgentSession"),
    ):
        build_agent_session()

    vad_kwargs = mock_vad.load.call_args.kwargs
    assert vad_kwargs["min_silence_duration"] >= 1.5, (
        "min_silence_duration was reduced below 1.5s — see issue #102: "
        "lower values cause mid-utterance pauses to split into multiple bubbles"
    )
