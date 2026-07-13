"""Unit tests for AgentTransferTool (Task 3 — agent routing foundation)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from taskorbit.tools.agent_transfer import (
    AgentTransferTool,
    resolve_builtin_transfer_target,
    resolve_transfer_target,
)


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


# ---------------------------------------------------------------------------
# Custom agent transfer — DB-backed validation
# ---------------------------------------------------------------------------


async def test_transfer_to_custom_agent_succeeds_with_db() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from taskorbit.database.models import AgentConfiguration

    fake_record = MagicMock(spec=AgentConfiguration)
    mock_db = AsyncMock()

    with patch(
        "taskorbit.database.crud.get_agent_configuration_by_id",
        new_callable=AsyncMock,
        return_value=fake_record,
    ):
        tool = AgentTransferTool(db=mock_db)
        result = await tool.execute({"target_agent_id": "abc123customagent"})

    assert result.success is True
    assert result.data["transferred_to"] == "abc123customagent"
    assert result.data["history_preserved"] is True


async def test_transfer_to_unknown_custom_agent_fails_with_db() -> None:
    from unittest.mock import AsyncMock

    mock_db = AsyncMock()

    # The resolver consults all three lookups (#212); none may match here.
    with (
        patch(
            "taskorbit.database.crud.get_agent_configuration_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "taskorbit.database.crud.get_default_agent_template",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "taskorbit.database.crud.get_agent_configuration_by_name",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        tool = AgentTransferTool(db=mock_db)
        result = await tool.execute({"target_agent_id": "nonexistent_custom_id"})

    assert result.success is False
    assert "nonexistent_custom_id" in result.error


async def test_transfer_to_custom_agent_fails_without_db() -> None:
    tool = AgentTransferTool(db=None)
    result = await tool.execute({"target_agent_id": "some_custom_id_not_builtin"})
    assert result.success is False


async def test_custom_agent_history_preserved_with_db() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from taskorbit.database.models import AgentConfiguration

    fake_record = MagicMock(spec=AgentConfiguration)
    mock_db = AsyncMock()
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]

    with patch(
        "taskorbit.database.crud.get_agent_configuration_by_id",
        new_callable=AsyncMock,
        return_value=fake_record,
    ):
        tool = AgentTransferTool(db=mock_db)
        result = await tool.execute({"target_agent_id": "abc123", "conversation_history": history})

    assert result.data["message_count"] == 2


# ---------------------------------------------------------------------------
# resolve_transfer_target() — the #212 resolution matrix
# ---------------------------------------------------------------------------


async def test_resolve_exact_builtin_name_without_db() -> None:
    resolved = await resolve_transfer_target("general_inquiry")
    assert resolved is not None
    assert resolved.canonical_id == "general_inquiry"
    assert resolved.kind == "builtin"


async def test_resolve_kebab_near_miss_via_keywords() -> None:
    # The exact prod value that broke #212: "inquiry-agent" is neither a
    # registry name nor a DB id, but the keyword map lands it on general_inquiry.
    resolved = await resolve_transfer_target("inquiry-agent")
    assert resolved is not None
    assert resolved.canonical_id == "general_inquiry"
    assert resolved.kind == "builtin"


async def test_resolve_display_name_with_spaces_and_case() -> None:
    resolved = await resolve_transfer_target("General Inquiry Agent")
    assert resolved is not None
    assert resolved.canonical_id == "general_inquiry"


async def test_resolve_capitalised_agent_suffix() -> None:
    # removesuffix("-agent") in the old normalisation was case-sensitive;
    # the keyword map is not.
    resolved = await resolve_transfer_target("General-Inquiry-Agent")
    assert resolved is not None
    assert resolved.canonical_id == "general_inquiry"


async def test_resolve_template_slug_with_db() -> None:
    from unittest.mock import AsyncMock, MagicMock

    mock_db = AsyncMock()
    fake_template = MagicMock()
    fake_template.name = "General Inquiry Agent"

    with (
        patch(
            "taskorbit.database.crud.get_agent_configuration_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "taskorbit.database.crud.get_default_agent_template",
            new_callable=AsyncMock,
            return_value=fake_template,
        ),
    ):
        resolved = await resolve_transfer_target("general-inquiry-agent", db=mock_db)

    assert resolved is not None
    assert resolved.canonical_id == "general-inquiry-agent"
    assert resolved.kind == "template"
    assert resolved.display_name == "General Inquiry Agent"


async def test_resolve_custom_agent_by_uuid_with_db() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from taskorbit.database.models import AgentConfiguration

    mock_db = AsyncMock()
    fake_record = MagicMock(spec=AgentConfiguration)
    fake_record.name = "John Max"

    with patch(
        "taskorbit.database.crud.get_agent_configuration_by_id",
        new_callable=AsyncMock,
        return_value=fake_record,
    ):
        resolved = await resolve_transfer_target(
            "33834dd8d88d4c73ab899a188f949a99", db=mock_db, user_id=1
        )

    assert resolved is not None
    assert resolved.canonical_id == "33834dd8d88d4c73ab899a188f949a99"
    assert resolved.kind == "config"


async def test_resolve_custom_agent_by_display_name_with_db() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from taskorbit.database.models import AgentConfiguration

    mock_db = AsyncMock()
    fake_record = MagicMock(spec=AgentConfiguration)
    fake_record.id = "row99"
    fake_record.name = "Max-Agent-Pizza"

    with (
        patch(
            "taskorbit.database.crud.get_agent_configuration_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "taskorbit.database.crud.get_default_agent_template",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "taskorbit.database.crud.get_agent_configuration_by_name",
            new_callable=AsyncMock,
            return_value=fake_record,
        ),
    ):
        resolved = await resolve_transfer_target("Max-Agent-Pizza", db=mock_db, user_id=1)

    assert resolved is not None
    assert resolved.canonical_id == "row99"
    assert resolved.kind == "config"


async def test_resolve_name_match_beats_keyword_fuzz() -> None:
    # A saved agent whose NAME contains a registry keyword ("tech") must
    # resolve to that saved agent, never fuzz-map to technical_support.
    from unittest.mock import AsyncMock, MagicMock

    from taskorbit.database.models import AgentConfiguration

    mock_db = AsyncMock()
    fake_record = MagicMock(spec=AgentConfiguration)
    fake_record.id = "row42"
    fake_record.name = "Tech Billing"

    with (
        patch(
            "taskorbit.database.crud.get_agent_configuration_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "taskorbit.database.crud.get_default_agent_template",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "taskorbit.database.crud.get_agent_configuration_by_name",
            new_callable=AsyncMock,
            return_value=fake_record,
        ),
    ):
        resolved = await resolve_transfer_target("Tech Billing", db=mock_db, user_id=1)

    assert resolved is not None
    assert resolved.canonical_id == "row42"
    assert resolved.kind == "config"


async def test_resolve_unknown_returns_none() -> None:
    assert await resolve_transfer_target("emergency-line-xyz") is None


async def test_resolve_empty_returns_none() -> None:
    assert await resolve_transfer_target("") is None
    assert await resolve_transfer_target("   ") is None


async def test_execute_resolves_inquiry_agent_to_general_inquiry() -> None:
    # End-to-end through the tool: the #212 prod config value now transfers.
    tool = AgentTransferTool()
    result = await tool.execute({"target_agent_id": "inquiry-agent"})
    assert result.success is True
    assert result.data["transferred_to"] == "general_inquiry"
    assert result.data["requested_target"] == "inquiry-agent"
    assert result.data["target_kind"] == "builtin"


# ---------------------------------------------------------------------------
# resolve_builtin_transfer_target() — sync subset used by tool selection (#212)
# ---------------------------------------------------------------------------


def test_builtin_resolver_exact_name() -> None:
    assert resolve_builtin_transfer_target("general_inquiry") == "general_inquiry"


def test_builtin_resolver_keyword_near_miss() -> None:
    assert resolve_builtin_transfer_target("inquiry-agent") == "general_inquiry"


def test_builtin_resolver_display_name() -> None:
    assert resolve_builtin_transfer_target("General Inquiry Agent") == "general_inquiry"


def test_builtin_resolver_unknown_returns_none() -> None:
    assert resolve_builtin_transfer_target("emergency-line-xyz") is None
    assert resolve_builtin_transfer_target("") is None
