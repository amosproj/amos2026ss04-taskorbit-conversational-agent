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

    refusal = "I'm here to help with product and ordering questions. I can't assist with that topic."
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

    refusal = "I'm here to help with product and ordering questions. I can't assist with that topic."
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
