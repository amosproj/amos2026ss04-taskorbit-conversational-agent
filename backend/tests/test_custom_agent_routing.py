"""Tests for custom-agent routing: ManualTransferRequest validation,
AgentRegistry DB fallback, multi-tenancy scoping, and _handle_manual_transfer."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import (
    AgentConfig,
    ConversationRequest,
    ConversationStatus,
    ManualTransferRequest,
    Message,
    MessageRole,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_config(**kwargs: Any) -> AgentConfig:
    defaults: dict[str, Any] = dict(id="agent-1", name="Bot", persona="Helpful bot", greeting="Hi!")
    defaults.update(kwargs)
    return AgentConfig(**defaults)


def _make_request(
    content: str = "Hello",
    manual_transfer: ManualTransferRequest | None = None,
) -> ConversationRequest:
    return ConversationRequest(
        conversation_id="conv-test",
        agent_config=_make_agent_config(),
        messages=[Message(role=MessageRole.USER, content=content)],
        manual_transfer=manual_transfer,
    )


def _make_db_record(config: dict[str, Any], record_id: str = "db-agent-id") -> MagicMock:
    """Return a mock AgentConfiguration ORM record."""
    record = MagicMock()
    record.id = record_id
    record.config = config
    return record


# ---------------------------------------------------------------------------
# ManualTransferRequest validation
# ---------------------------------------------------------------------------


class TestManualTransferRequestValidation:
    def test_valid_with_id_only(self) -> None:
        req = ManualTransferRequest(target_agent_id="abc123")
        assert req.target_agent_id == "abc123"

    def test_valid_with_name_only(self) -> None:
        req = ManualTransferRequest(target_agent_name="Sales Agent")
        assert req.target_agent_name == "Sales Agent"

    def test_valid_with_both_fields(self) -> None:
        req = ManualTransferRequest(target_agent_id="abc", target_agent_name="Sales")
        assert req.target_agent_id == "abc"

    def test_invalid_when_both_none(self) -> None:
        with pytest.raises(ValidationError, match="at least one of target_agent_id"):
            ManualTransferRequest()

    def test_invalid_when_both_empty_strings(self) -> None:
        with pytest.raises(ValidationError, match="at least one of target_agent_id"):
            ManualTransferRequest(target_agent_id="", target_agent_name="")


# ---------------------------------------------------------------------------
# AgentRegistry.create_by_name — DB fallback with user_id scoping
# ---------------------------------------------------------------------------


class TestAgentRegistryCreateByName:
    @pytest.mark.asyncio
    async def test_builtin_agent_resolved_without_db(self) -> None:
        from taskorbit.agents import AgentRegistry, SalesAgent

        orch = MagicMock()
        agent = await AgentRegistry.create_by_name("sales", _make_agent_config(), orch, db=None)
        assert isinstance(agent, SalesAgent)

    @pytest.mark.asyncio
    async def test_db_fallback_passes_user_id(self) -> None:
        from taskorbit.agents import AgentRegistry

        custom_config_dict = dict(
            id="custom-1", name="Custom", persona="Custom persona", greeting="Hi"
        )
        db = AsyncMock()
        record = _make_db_record(custom_config_dict)

        with patch(
            "taskorbit.database.crud.get_agent_configuration_by_name",
            new_callable=AsyncMock,
            return_value=record,
        ) as mock_lookup:
            orch = MagicMock()
            agent = await AgentRegistry.create_by_name(
                "unknown-intent", _make_agent_config(), orch, db=db, user_id=42
            )

        mock_lookup.assert_called_once_with(db, "unknown-intent", user_id=42)
        assert agent.agent_name == "custom-1"

    @pytest.mark.asyncio
    async def test_db_fallback_uses_none_user_id_when_omitted(self) -> None:
        from taskorbit.agents import AgentRegistry

        db = AsyncMock()

        with patch(
            "taskorbit.database.crud.get_agent_configuration_by_name",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_lookup:
            orch = MagicMock()
            await AgentRegistry.create_by_name("unknown-intent", _make_agent_config(), orch, db=db)

        mock_lookup.assert_called_once_with(db, "unknown-intent", user_id=None)

    @pytest.mark.asyncio
    async def test_falls_back_to_default_when_db_returns_none(self) -> None:
        from taskorbit.agents import AgentRegistry

        db = AsyncMock()

        with patch(
            "taskorbit.database.crud.get_agent_configuration_by_name",
            new_callable=AsyncMock,
            return_value=None,
        ):
            orch = MagicMock()
            agent = await AgentRegistry.create_by_name(
                "completely-unknown", _make_agent_config(), orch, db=db, user_id=1
            )

        # Falls back to GenericAgent using config.id (which is "agent-1" from _make_agent_config)
        assert agent.agent_name == "agent-1"

    @pytest.mark.asyncio
    async def test_invalid_config_in_db_falls_back_to_default(self) -> None:
        """A corrupt record.config must not crash the pipeline — fall back to default."""
        from taskorbit.agents import AgentRegistry

        db = AsyncMock()
        bad_record = _make_db_record({"totally": "wrong"})

        with patch(
            "taskorbit.database.crud.get_agent_configuration_by_name",
            new_callable=AsyncMock,
            return_value=bad_record,
        ):
            orch = MagicMock()
            agent = await AgentRegistry.create_by_name(
                "unknown", _make_agent_config(), orch, db=db, user_id=1
            )

        # Must not raise; falls back gracefully
        assert agent is not None


# ---------------------------------------------------------------------------
# _handle_manual_transfer — scoping and recursion guard
# ---------------------------------------------------------------------------


class TestHandleManualTransfer:
    def _make_orch_with_mock_llm(self, reply: str = "Transferred!") -> ConversationOrchestrator:
        orch = ConversationOrchestrator()
        orch._call_llm = AsyncMock(return_value=reply)  # type: ignore[method-assign]
        return orch

    @pytest.mark.asyncio
    async def test_manual_transfer_cleared_before_re_entering_pipeline(
        self,
        mock_good_intent: Any,  # noqa: ARG002
    ) -> None:
        """manual_transfer=None on the re-entered request prevents infinite recursion.

        We intercept the second call to process_message (the re-entry after config swap)
        and capture its request object to verify manual_transfer was cleared.
        """
        orch = self._make_orch_with_mock_llm()
        target_config = dict(id="target-1", name="Target", persona="Target persona", greeting="Hi")
        db = AsyncMock()

        captured_re_entry: list[ConversationRequest] = []

        original_process = ConversationOrchestrator.process_message

        call_count = {"n": 0}

        async def spy_process(
            self_: Any,
            req: ConversationRequest,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            call_count["n"] += 1
            if call_count["n"] > 1:
                # This is the re-entered call — capture it before delegating
                captured_re_entry.append(req)
            return await original_process(self_, req, *args, **kwargs)

        with (
            patch(
                "taskorbit.database.crud.get_agent_configuration_by_id",
                new_callable=AsyncMock,
                return_value=_make_db_record(target_config, record_id="target-1"),
            ),
            patch.object(ConversationOrchestrator, "process_message", spy_process),
        ):
            req = _make_request(manual_transfer=ManualTransferRequest(target_agent_id="target-1"))
            await orch.process_message(req, db=db)

        assert captured_re_entry, "process_message should have been called a second time"
        re_entered = captured_re_entry[0]
        assert (
            re_entered.manual_transfer is None
        ), "Re-entered request must have manual_transfer=None"
        assert re_entered.agent_config.id == "target-1"

    @pytest.mark.asyncio
    async def test_manual_transfer_name_lookup_scoped_to_user_id(self) -> None:
        """get_agent_configuration_by_name must receive user_id from _handle_manual_transfer."""
        orch = self._make_orch_with_mock_llm()
        target_config = dict(id="named-agent", name="Named", persona="Named persona", greeting="Hi")
        db = AsyncMock()

        with (
            patch(
                "taskorbit.database.crud.get_agent_configuration_by_name",
                new_callable=AsyncMock,
                return_value=_make_db_record(target_config, record_id="named-agent"),
            ) as mock_name_lookup,
            patch(
                "taskorbit.database.crud.get_agent_configuration_by_id",
                new_callable=AsyncMock,
                return_value=_make_db_record(target_config, record_id="named-agent"),
            ),
        ):
            req = _make_request(manual_transfer=ManualTransferRequest(target_agent_name="Named"))
            await orch._handle_manual_transfer(req, db, user_id=99)

        mock_name_lookup.assert_called_once_with(db, "Named", user_id=99)

    @pytest.mark.asyncio
    async def test_manual_transfer_returns_error_when_agent_not_found(self) -> None:
        orch = ConversationOrchestrator()
        db = AsyncMock()

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
        ):
            req = _make_request(
                manual_transfer=ManualTransferRequest(target_agent_id="nonexistent")
            )
            response = await orch._handle_manual_transfer(req, db, user_id=1)

        assert response.status == ConversationStatus.ERROR
        assert "manual_transfer_agent_config_missing" in response.error

    @pytest.mark.asyncio
    async def test_manual_transfer_invalid_config_returns_error(self) -> None:
        orch = ConversationOrchestrator()
        db = AsyncMock()
        bad_record = _make_db_record({"not": "a valid AgentConfig"})

        with patch(
            "taskorbit.database.crud.get_agent_configuration_by_id",
            new_callable=AsyncMock,
            return_value=bad_record,
        ):
            req = _make_request(manual_transfer=ManualTransferRequest(target_agent_id="bad-config"))
            response = await orch._handle_manual_transfer(req, db, user_id=1)

        assert response.status == ConversationStatus.ERROR
