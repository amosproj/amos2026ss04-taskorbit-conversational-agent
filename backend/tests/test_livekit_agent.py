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

    mock_vad.load.assert_called_once_with()
    mock_stt.assert_called_once_with(
        api_key=_FAKE_DG_KEY,
        model=_FAKE_DG_MODEL,
        language=_FAKE_DG_LANG,
    )
    mock_tts.assert_called_once_with(
        api_key=_FAKE_EL_KEY,
        voice_id=_FAKE_EL_VOICE,
        model=_FAKE_EL_MODEL,
    )
    mock_session.assert_called_once()
    kwargs = mock_session.call_args.kwargs
    assert kwargs["vad"] is mock_vad.load.return_value
    assert kwargs["stt"] is mock_stt.return_value
    assert kwargs["tts"] is mock_tts.return_value
    # Session uses manual endpointing (push-to-talk); no allow_interruptions flag.
    assert kwargs["turn_handling"]["endpointing"]["mode"] == "manual"


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
