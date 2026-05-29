"""Tests for ConversationOrchestrator."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import (
    AgentConfig,
    ContextLimitConfig,
    ConversationRequest,
    Message,
    MessageRole,
    PersonaConstraints,
)


def _make_request(content: str = "Hello") -> ConversationRequest:
    return ConversationRequest(
        conversation_id="conv-test",
        agent_config=AgentConfig(
            id="agent-1",
            name="Bot",
            persona="Helpful bot",
            greeting="Hi!",
        ),
        messages=[Message(role=MessageRole.USER, content=content)],
    )


def test_orchestrator_instantiates() -> None:
    orch = ConversationOrchestrator()
    assert orch is not None


@pytest.mark.asyncio
async def test_process_message_returns_mocked_llm_reply() -> None:
    orch = ConversationOrchestrator()
    mock_reply = '[Mocked LLM] I received: "Hello there"'

    with patch.object(ConversationOrchestrator, "_call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_reply
        response = await orch.process_message(_make_request("Hello there"))

        assert response.conversation_id == "conv-test"
        assert response.reply.role == MessageRole.ASSISTANT
        assert response.reply.content == mock_reply


@pytest.mark.asyncio
async def test_process_message_returns_error_on_empty_messages() -> None:
    req = ConversationRequest(
        conversation_id="conv-empty",
        agent_config=AgentConfig(
            id="agent-1",
            name="Bot",
            persona="Helpful bot",
            greeting="Hi!",
        ),
        messages=[],
    )
    orch = ConversationOrchestrator()
    response = await orch.process_message(req)
    assert response.reply.role == MessageRole.ASSISTANT
    assert response.status == "error"
    assert "No user message content found" in response.error


@pytest.mark.asyncio
async def test_process_message_timeout_handling() -> None:
    # Use settings with a very short timeout for testing
    from taskorbit.config import Settings

    settings = Settings(llm_timeout_seconds=0.01)
    orch = ConversationOrchestrator(settings=settings)

    # Mock _call_llm to sleep longer than the timeout
    async def slow_llm(*args: Any, **kwargs: Any) -> str:
        await asyncio.sleep(1.0)
        return "too slow"

    with patch.object(ConversationOrchestrator, "_call_llm", side_effect=slow_llm):
        response = await orch.process_message(_make_request())
        assert response.status == "error"
        assert "timed out after 0.01 seconds" in response.error
        assert "trouble connecting to my brain" in response.reply.content


# ---------------------------------------------------------------------------
# conversation_errors_total metric
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_increments_conversation_errors_total() -> None:
    from taskorbit.config import Settings

    settings = Settings(llm_timeout_seconds=0.01)
    orch = ConversationOrchestrator(settings=settings)
    mock_metrics = MagicMock()

    async def slow_llm(*args: Any, **kwargs: Any) -> str:
        await asyncio.sleep(1.0)
        return "too slow"

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        with patch.object(ConversationOrchestrator, "_call_llm", side_effect=slow_llm):
            response = await orch.process_message(_make_request())

    assert response.status == "error"
    mock_metrics.conversation_errors_total.labels(error_type="llm_timeout").inc.assert_called_once()


@pytest.mark.asyncio
async def test_runtime_error_increments_conversation_errors_total() -> None:
    orch = ConversationOrchestrator()
    mock_metrics = MagicMock()

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        with patch.object(
            ConversationOrchestrator,
            "_call_llm",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected boom"),
        ):
            response = await orch.process_message(_make_request())

    assert response.status == "error"
    mock_metrics.conversation_errors_total.labels(
        error_type="runtime_error"
    ).inc.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_input_increments_conversation_errors_total() -> None:
    orch = ConversationOrchestrator()
    mock_metrics = MagicMock()

    empty_req = ConversationRequest(
        conversation_id="conv-empty",
        agent_config=AgentConfig(id="a", name="Bot", persona="p", greeting="hi"),
        messages=[],
    )

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        response = await orch.process_message(empty_req)

    assert response.status == "error"
    mock_metrics.conversation_errors_total.labels(
        error_type="invalid_input"
    ).inc.assert_called_once()


# ---------------------------------------------------------------------------
# _build_system_prompt + persona_constraints
# ---------------------------------------------------------------------------

# These tests verify that the orchestrator correctly appends
# persona constraints using the new imperative headers (CORE CONSTRAINT).


def _agent_with_constraints(constraints: PersonaConstraints | None) -> AgentConfig:
    return AgentConfig(
        id="agent-1",
        name="John",
        persona="TechStore customer support.",
        greeting="Hi!",
        persona_constraints=constraints,
    )


def test_build_system_prompt_without_constraints_unchanged() -> None:
    """With no persona_constraints the prompt is exactly the existing format."""
    orch = ConversationOrchestrator()
    prompt = orch._build_system_prompt(_agent_with_constraints(None), active_tool=None)
    assert prompt == "You are John.\nPersona: TechStore customer support."


def test_build_system_prompt_includes_persona_constraints() -> None:
    """Populated constraints append scope, out_of_scope, and refusal_template lines."""
    constraints = PersonaConstraints(
        scope="TechStore customer service: orders, returns, accounts.",
        out_of_scope=["therapy", "legal advice"],
        refusal_template="I can only help with TechStore questions.",
    )
    orch = ConversationOrchestrator()
    prompt = orch._build_system_prompt(_agent_with_constraints(constraints), active_tool=None)

    assert prompt.startswith("You are John.\nPersona: TechStore customer support.")
    # Asserting against the new imperative headers
    assert (
        "CORE CONSTRAINT - Authorized Scope: TechStore customer service: orders, returns, accounts."
        in prompt
    )
    assert (
        "CORE CONSTRAINT - Forbidden Topics (you MUST politely refuse and redirect): therapy, legal advice"
        in prompt
    )
    assert (
        'REQUIRED REFUSAL PHRASE (use this for redirection): "I can only help with TechStore questions."'
        in prompt
    )


def test_build_system_prompt_empty_constraints_object_is_noop() -> None:
    """A PersonaConstraints with every field empty leaves the prompt unchanged."""
    orch = ConversationOrchestrator()
    prompt = orch._build_system_prompt(
        _agent_with_constraints(PersonaConstraints()), active_tool=None
    )
    assert prompt == "You are John.\nPersona: TechStore customer support."


# ---------------------------------------------------------------------------
# _truncate_messages — conversation-history FIFO cap (LLM memory safeguards)
# ---------------------------------------------------------------------------


def _msg(role: MessageRole, content: str) -> Message:
    return Message(role=role, content=content)


def _conversation(count: int) -> list[Message]:
    """Build alternating user/assistant turns: u0, a0, u1, a1, ..."""
    out: list[Message] = []
    for i in range(count):
        role = MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT
        out.append(_msg(role, f"msg-{i}"))
    return out


def test_truncate_messages_returns_unchanged_when_no_context_limit() -> None:
    """No config → full history is passed through verbatim."""
    orch = ConversationOrchestrator()
    msgs = _conversation(20)
    assert orch._truncate_messages(msgs, None) == msgs


def test_truncate_messages_returns_unchanged_when_under_limit() -> None:
    """History smaller than the cap is returned untouched."""
    orch = ConversationOrchestrator()
    msgs = _conversation(10)
    result = orch._truncate_messages(msgs, ContextLimitConfig(type="message_count", value=50))
    assert result == msgs


def test_truncate_messages_drops_oldest_fifo_when_over_limit() -> None:
    """FIFO: oldest non-system messages are removed first."""
    orch = ConversationOrchestrator()
    msgs = _conversation(100)
    result = orch._truncate_messages(msgs, ContextLimitConfig(type="message_count", value=10))
    assert len(result) == 10
    # The first kept message should be msg-90; last should be msg-99.
    assert result[0].content == "msg-90"
    assert result[-1].content == "msg-99"


def test_truncate_messages_preserves_system_prompt_at_minimum_limit() -> None:
    """Acceptance criterion: system prompt is NEVER dropped (schema min limit = 10)."""
    orch = ConversationOrchestrator()
    system = _msg(MessageRole.SYSTEM, "You are TaskOrbit.")
    msgs = [system, *_conversation(30)]
    result = orch._truncate_messages(msgs, ContextLimitConfig(type="message_count", value=10))
    # System prompt survives + exactly 10 most recent conversation messages kept.
    assert result[0] is system
    assert len(result) == 11
    assert result[1].content == "msg-20"
    assert result[-1].content == "msg-29"


def test_truncate_messages_preserves_multiple_system_messages() -> None:
    """All system messages are protected regardless of position."""
    orch = ConversationOrchestrator()
    sys1 = _msg(MessageRole.SYSTEM, "sys-1")
    sys2 = _msg(MessageRole.SYSTEM, "sys-2")
    # 30 non-system messages, split around a second system message.
    msgs = [sys1, *_conversation(15), sys2, *_conversation(15)]
    result = orch._truncate_messages(msgs, ContextLimitConfig(type="message_count", value=10))
    # Both system messages present; only the last 10 non-system kept.
    system_results = [m for m in result if m.role == MessageRole.SYSTEM]
    other_results = [m for m in result if m.role != MessageRole.SYSTEM]
    assert system_results == [sys1, sys2]
    assert len(other_results) == 10


def test_truncate_messages_logs_truncation_event() -> None:
    """Truncation must emit a structured log line with counts (for observability)."""
    orch = ConversationOrchestrator()
    msgs = _conversation(30)
    with patch("taskorbit.orchestration.logger") as mock_logger:
        orch._truncate_messages(msgs, ContextLimitConfig(type="message_count", value=10))
        mock_logger.info.assert_called_once()
        call_kwargs = mock_logger.info.call_args.kwargs
        assert mock_logger.info.call_args.args[0] == "message_truncation_applied"
        assert call_kwargs["original_count"] == 30
        assert call_kwargs["trimmed_count"] == 10
        assert call_kwargs["dropped_count"] == 20


def test_truncate_messages_does_not_log_when_under_limit() -> None:
    """No truncation → no log noise."""
    orch = ConversationOrchestrator()
    msgs = _conversation(5)
    with patch("taskorbit.orchestration.logger") as mock_logger:
        orch._truncate_messages(msgs, ContextLimitConfig(type="message_count", value=50))
        mock_logger.info.assert_not_called()


def test_context_limit_rejects_unsupported_strategy() -> None:
    """Only 'message_count' is enforced this sprint; the schema rejects others."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ContextLimitConfig(type="token_threshold", value=100)  # type: ignore[arg-type]
