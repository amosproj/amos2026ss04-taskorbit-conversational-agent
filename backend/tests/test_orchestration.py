"""Tests for ConversationOrchestrator."""

from __future__ import annotations

import pytest

from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import AgentConfig, ConversationRequest, Message, MessageRole


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
async def test_process_message_returns_echo_reply() -> None:
    orch = ConversationOrchestrator()
    response = await orch.process_message(_make_request("Hello there"))
    assert response.conversation_id == "conv-test"
    assert response.reply.role == MessageRole.ASSISTANT
    assert "Hello there" in response.reply.content


@pytest.mark.asyncio
async def test_process_message_greets_on_empty_messages() -> None:
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
    assert len(response.reply.content) > 0
