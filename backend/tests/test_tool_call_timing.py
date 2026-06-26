"""Tests for tool-call latency instrumentation (#68)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.tools import ToolResult
from taskorbit.types import (
    AgentConfig,
    ConfirmationConfig,
    ConversationRequest,
    Message,
    MessageRole,
    ToolDefinition,
    ToolType,
)


def _make_request(content: str = "Hello") -> ConversationRequest:
    return ConversationRequest(
        conversation_id="conv-timing",
        agent_config=AgentConfig(
            id="agent-1",
            name="Bot",
            persona="Helpful bot",
            greeting="Hi!",
        ),
        messages=[Message(role=MessageRole.USER, content=content)],
    )


@pytest.mark.asyncio
async def test_dispatch_tool_records_latency_and_metric() -> None:
    orch = ConversationOrchestrator()
    tool = ToolDefinition(
        id="end-call",
        name="end_call",
        type=ToolType.END_CALL,
        description="end",
        confirmation=ConfirmationConfig(required=False, prompt=""),
    )
    mock_metrics = MagicMock()

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        with patch(
            "taskorbit.tools.end_call.EndCallTool.execute",
            new_callable=AsyncMock,
            return_value=ToolResult(success=True, data={"ended": True}),
        ):
            data, elapsed = await orch._dispatch_tool(tool, {})

    assert data == {"ended": True}
    assert elapsed > 0
    mock_metrics.pipeline_latency_seconds.labels.assert_called_with(stage="tool_call")
    mock_metrics.pipeline_latency_seconds.labels.return_value.observe.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_includes_latency_ms_on_success(mock_good_intent: Any) -> None:
    orch = ConversationOrchestrator()

    with patch.object(
        ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
    ):
        response = await orch.process_message(_make_request("Hello there"))

    assert response.latency_ms is not None
    assert response.latency_ms.llm_call is not None
    assert response.latency_ms.llm_call > 0
    assert response.latency_ms.total is not None
    assert response.latency_ms.total >= response.latency_ms.llm_call
