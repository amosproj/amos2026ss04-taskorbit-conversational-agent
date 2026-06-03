"""Unit tests for AgentTransferTool (Task 3 — agent routing foundation)."""

from __future__ import annotations

import pytest

from taskorbit.tools.agent_transfer import AgentTransferTool


@pytest.fixture
def tool() -> AgentTransferTool:
    return AgentTransferTool()


# ---------------------------------------------------------------------------
# execute() — success paths
# ---------------------------------------------------------------------------


async def test_transfer_to_technical_support_succeeds(tool: AgentTransferTool) -> None:
    result = await tool.execute({"target_agent_id": "technical_support"})
    assert result.success is True
    assert result.data["transferred_to"] == "technical_support"


async def test_transfer_to_general_inquiry_succeeds(tool: AgentTransferTool) -> None:
    result = await tool.execute({"target_agent_id": "general_inquiry"})
    assert result.success is True
    assert result.data["transferred_to"] == "general_inquiry"


async def test_transfer_to_appointment_management_succeeds(tool: AgentTransferTool) -> None:
    result = await tool.execute({"target_agent_id": "appointment_management"})
    assert result.success is True


async def test_transfer_to_sales_succeeds(tool: AgentTransferTool) -> None:
    result = await tool.execute({"target_agent_id": "sales"})
    assert result.success is True


async def test_history_preserved_flag_is_true(tool: AgentTransferTool) -> None:
    result = await tool.execute({"target_agent_id": "technical_support"})
    assert result.data["history_preserved"] is True


async def test_message_count_reflects_history_length(tool: AgentTransferTool) -> None:
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    result = await tool.execute(
        {"target_agent_id": "general_inquiry", "conversation_history": history}
    )
    assert result.data["message_count"] == 2


async def test_empty_history_defaults_to_zero(tool: AgentTransferTool) -> None:
    result = await tool.execute({"target_agent_id": "sales"})
    assert result.data["message_count"] == 0


# ---------------------------------------------------------------------------
# execute() — failure paths
# ---------------------------------------------------------------------------


async def test_missing_target_agent_id_returns_failure(tool: AgentTransferTool) -> None:
    result = await tool.execute({})
    assert result.success is False
    assert "target_agent_id" in result.error


async def test_empty_target_agent_id_returns_failure(tool: AgentTransferTool) -> None:
    result = await tool.execute({"target_agent_id": "   "})
    assert result.success is False


async def test_unknown_agent_id_returns_failure(tool: AgentTransferTool) -> None:
    result = await tool.execute({"target_agent_id": "nonexistent_agent"})
    assert result.success is False
    assert "nonexistent_agent" in result.error


async def test_unknown_agent_error_lists_valid_agents(tool: AgentTransferTool) -> None:
    result = await tool.execute({"target_agent_id": "bad_agent"})
    assert "technical_support" in result.error or "sales" in result.error


# ---------------------------------------------------------------------------
# validate_parameters()
# ---------------------------------------------------------------------------


def test_validate_returns_true_for_known_agent(tool: AgentTransferTool) -> None:
    assert tool.validate_parameters({"target_agent_id": "technical_support"}) is True


def test_validate_returns_false_for_unknown_agent(tool: AgentTransferTool) -> None:
    assert tool.validate_parameters({"target_agent_id": "unknown_xyz"}) is False


def test_validate_returns_false_for_empty_id(tool: AgentTransferTool) -> None:
    assert tool.validate_parameters({"target_agent_id": ""}) is False


def test_validate_returns_false_for_missing_key(tool: AgentTransferTool) -> None:
    assert tool.validate_parameters({}) is False
