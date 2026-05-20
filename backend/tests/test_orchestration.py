"""Tests for ConversationOrchestrator."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
