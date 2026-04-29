"""Tests for ConversationOrchestrator skeleton."""

from __future__ import annotations

import pytest

from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import AgentConfig, ConversationRequest, Message, MessageRole


def _make_request() -> ConversationRequest:
    return ConversationRequest(
        conversation_id="conv-test",
        agent_config=AgentConfig(
            id="agent-1",
            name="Bot",
            persona="Helpful bot",
            greeting="Hi!",
        ),
        messages=[Message(role=MessageRole.USER, content="Hello")],
    )


def test_orchestrator_instantiates() -> None:
    orch = ConversationOrchestrator()
    assert orch is not None


@pytest.mark.asyncio
async def test_process_message_raises_not_implemented() -> None:
    orch = ConversationOrchestrator()
    with pytest.raises(NotImplementedError):
        await orch.process_message(_make_request())
