"""Behavioral tests for persona guardrails (ticket #168).

These tests assert the desired behavior *after* enforcement is implemented:
- Off-topic user messages (matching out_of_scope) should be refused by the
  orchestrator before any LLM call and the configured refusal_template should
  be returned verbatim.
- In-scope queries should proceed to the LLM as today.

Note: these tests are expected to fail on current `main` because enforcement
is not yet implemented (guardrails are prompt-only). They serve as CI
regression tests to prevent re-introduction of the regression once the
pre-LLM scope check is implemented.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.config import Settings
from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import (
    AgentConfig,
    ConversationRequest,
    ConversationResponse,
    ConversationStatus,
    Message,
    MessageRole,
    PersonaConstraints,
)


def _make_orchestrator() -> ConversationOrchestrator:
    settings = Settings(openai_api_key="sk-test-key", google_api_key="AIza-test-key")
    return ConversationOrchestrator(settings=settings)


@pytest.mark.asyncio
async def test_off_topic_refuses(mock_good_intent) -> None:
    """Off-topic input should return the refusal template and NOT call the LLM."""
    orchestrator = _make_orchestrator()

    refusal = (
        "I'm here to help with product and ordering questions. I can't assist with that topic."
    )
    agent = AgentConfig(
        id="demo-agent",
        name="Demo Agent",
        persona="Product & ordering assistant",
        greeting="Hi!",
        persona_constraints=PersonaConstraints(
            scope="Product & ordering questions for TechStore",
            out_of_scope=["recipes", "cooking"],
            refusal_template=refusal,
        ),
    )

    request = ConversationRequest(
        conversation_id="conv-off-topic",
        agent_config=agent,
        messages=[Message(role=MessageRole.USER, content="How do you make pizza?")],
    )

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="Here's a great pizza recipe...")

    with patch("taskorbit.integrations.llm.factory.get_llm_client", return_value=mock_client):
        response = await orchestrator.process_message(request)

    # Behavioural assertion: refusal is returned and LLM was NOT invoked.
    assert response.reply is not None
    assert refusal in response.reply.content
    mock_client.generate.assert_not_called()


@pytest.mark.asyncio
async def test_in_scope_calls_llm_and_returns_answer(mock_good_intent) -> None:
    """In-scope input should call the LLM and return its text."""
    orchestrator = _make_orchestrator()

    refusal = (
        "I'm here to help with product and ordering questions. I can't assist with that topic."
    )
    agent = AgentConfig(
        id="demo-agent",
        name="Demo Agent",
        persona="Product & ordering assistant",
        greeting="Hi!",
        persona_constraints=PersonaConstraints(
            scope="Product & ordering questions for TechStore",
            out_of_scope=["recipes", "cooking"],
            refusal_template=refusal,
        ),
    )

    request = ConversationRequest(
        conversation_id="conv-in-scope",
        agent_config=agent,
        messages=[Message(role=MessageRole.USER, content="What's your return policy?")],
    )

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="Our return policy is 30 days from delivery.")

    with patch("taskorbit.integrations.llm.factory.get_llm_client", return_value=mock_client):
        response = await orchestrator.process_message(request)

    assert response.reply is not None
    assert "return policy" in response.reply.content.lower()
    assert mock_client.generate.call_count >= 1


@pytest.mark.asyncio
async def test_stream_off_topic_refuses_before_dispatch(mock_good_intent) -> None:
    """#168 voice/stream parity: an off-topic message on the streaming path is
    refused before any slot-extraction LLM call or tool dispatch, and nothing is
    streamed. This closes the gap the text path already covered (the voice bug
    where an off-topic turn could run extraction/dispatch before being refused).
    """
    orchestrator = _make_orchestrator()

    refusal = "I'm here to help with TechStore questions. I can't assist with that topic."
    agent = AgentConfig(
        id="demo-agent",
        name="Demo Agent",
        persona="Product & ordering assistant",
        greeting="Hi!",
        persona_constraints=PersonaConstraints(
            scope="Product & ordering questions for TechStore",
            out_of_scope=["recipes", "cooking"],
            refusal_template=refusal,
        ),
    )
    request = ConversationRequest(
        conversation_id="conv-stream-off-topic",
        agent_config=agent,
        messages=[Message(role=MessageRole.USER, content="How do you make pizza?")],
    )

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="Here's a pizza recipe...")
    mock_client.generate_stream = MagicMock()

    with patch("taskorbit.integrations.llm.factory.get_llm_client", return_value=mock_client):
        items = [item async for item in orchestrator.process_message_stream(request)]

    chunks = [i for i in items if isinstance(i, str)]
    responses = [i for i in items if isinstance(i, ConversationResponse)]
    assert chunks == []  # nothing streamed to the caller
    assert responses, "expected a refusal response"
    assert refusal in responses[-1].reply.content
    assert responses[-1].status == ConversationStatus.REJECTED
    mock_client.generate_stream.assert_not_called()  # streaming LLM never reached
    mock_client.generate.assert_not_called()  # no slot-extraction LLM call either


@pytest.mark.asyncio
async def test_stream_in_scope_still_streams_answer(mock_good_intent) -> None:
    """#168 cross-dependency: an in-scope message on the streaming path still
    reaches the LLM and streams its answer. The guardrail must not block
    legitimate turns (data extraction / tool execution stay intact).
    """
    orchestrator = _make_orchestrator()

    refusal = "I can't assist with that topic."
    agent = AgentConfig(
        id="demo-agent",
        name="Demo Agent",
        persona="Product & ordering assistant",
        greeting="Hi!",
        persona_constraints=PersonaConstraints(
            scope="Product & ordering questions for TechStore",
            out_of_scope=["recipes", "cooking"],
            refusal_template=refusal,
        ),
    )
    request = ConversationRequest(
        conversation_id="conv-stream-in-scope",
        agent_config=agent,
        messages=[Message(role=MessageRole.USER, content="What's your return policy?")],
    )

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="")

    async def _fake_stream(*_args, **_kwargs):
        yield "Our return policy is 30 days from delivery."

    mock_client.generate_stream = MagicMock(side_effect=_fake_stream)

    with patch("taskorbit.integrations.llm.factory.get_llm_client", return_value=mock_client):
        items = [item async for item in orchestrator.process_message_stream(request)]

    chunks = [i for i in items if isinstance(i, str)]
    responses = [i for i in items if isinstance(i, ConversationResponse)]
    assert "return policy" in "".join(chunks).lower()
    mock_client.generate_stream.assert_called()
    assert all(r.status != ConversationStatus.REJECTED for r in responses)
