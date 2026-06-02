"""Tests for ConversationOrchestrator."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import (
    AgentConfig,
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
# Routing pipeline (#8 Task 7)
# ---------------------------------------------------------------------------


def _intent_result(
    name: str = "book_service_appointment",
    agent_name: str = "sales",
    confidence: float = 0.9,
    requires_clarification: bool = False,
    required_inputs: list[dict[str, Any]] | None = None,
) -> Any:
    from taskorbit.intent import IntentResult

    return IntentResult(
        name=name,
        description="test",
        agent_name=agent_name,
        required_inputs=required_inputs or [],
        confidence=confidence,
        requires_clarification=requires_clarification,
    )


@pytest.mark.asyncio
async def test_clarification_short_circuits_pipeline() -> None:
    """Low confidence intent skips LLM call and returns CLARIFICATION status."""
    from taskorbit.intent import _CLARIFICATION_REPLY

    orch = ConversationOrchestrator()
    low_conf = _intent_result(confidence=0.3, requires_clarification=True)

    with patch.object(orch._intent_router, "detect", new_callable=AsyncMock) as mock_detect:
        mock_detect.return_value = low_conf
        with patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock
        ) as mock_llm:
            response = await orch.process_message(_make_request("uhh maybe?"))

    assert response.status == "clarification"
    assert response.selected_agent == ""
    assert response.reply.content == _CLARIFICATION_REPLY
    mock_llm.assert_not_called()  # short-circuit means no LLM call


@pytest.mark.asyncio
async def test_routed_agent_matches_intent_agent_name() -> None:
    """selected_agent in response mirrors intent.agent_name from the router."""
    orch = ConversationOrchestrator()
    intent = _intent_result(
        name="customer_dissatisfaction_inquiry", agent_name="customer_dissatisfaction"
    )

    with patch.object(orch._intent_router, "detect", new_callable=AsyncMock) as mock_detect:
        mock_detect.return_value = intent
        with patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
        ):
            response = await orch.process_message(_make_request("I'm unhappy"))

    assert response.selected_intent == "customer_dissatisfaction_inquiry"
    assert response.selected_agent == "customer_dissatisfaction"


@pytest.mark.asyncio
async def test_agent_transfer_dispatch_sets_tool_invoked() -> None:
    """When an agent_transfer tool fires, response.tool_invoked is populated."""
    from taskorbit.slots.models import SlotExtractionResult, SlotValue
    from taskorbit.types import ConfirmationConfig, ToolDefinition, ToolType

    orch = ConversationOrchestrator()
    intent = _intent_result(
        required_inputs=[{"name": "caller_name", "type": "string", "required": True}]
    )
    transfer_tool = ToolDefinition(
        id="transfer-1",
        name="agent_transfer",
        type=ToolType.AGENT_TRANSFER,
        description="hand off",
        confirmation=ConfirmationConfig(required=False, prompt=""),
        parameters={"targets": ["technical_support"]},
    )
    slot_result = SlotExtractionResult(
        filled={"caller_name": SlotValue(name="caller_name", value="Asad", slot_type="string")},
        missing=[],
    )

    with (
        patch.object(orch._intent_router, "detect", new_callable=AsyncMock, return_value=intent),
        patch.object(ConversationOrchestrator, "_select_active_tool", return_value=transfer_tool),
        patch.object(
            ConversationOrchestrator,
            "_extract_slots",
            new_callable=AsyncMock,
            return_value=slot_result,
        ),
        patch.object(
            ConversationOrchestrator,
            "_dispatch_tool",
            new_callable=AsyncMock,
            return_value={"transferred_to": "technical_support", "history_preserved": True},
        ),
        patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
        ),
    ):
        response = await orch.process_message(_make_request("transfer me"))

    assert response.tool_invoked is not None
    assert response.tool_invoked.type == ToolType.AGENT_TRANSFER


@pytest.mark.asyncio
async def test_unknown_intent_falls_back_via_clarification() -> None:
    """When the LLM returns no matching intent, the router's _FALLBACK_RESULT
    surfaces as a clarification response — no 500 error, no LLM call for reply."""
    from taskorbit.intent import _CLARIFICATION_REPLY, _FALLBACK_RESULT

    orch = ConversationOrchestrator()

    with patch.object(
        orch._intent_router, "detect", new_callable=AsyncMock, return_value=_FALLBACK_RESULT
    ):
        with patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock
        ) as mock_llm:
            response = await orch.process_message(_make_request("blibber blabber"))

    assert response.status == "clarification"
    assert response.selected_intent == "unknown"
    assert response.selected_agent == ""
    assert response.reply.content == _CLARIFICATION_REPLY
    mock_llm.assert_not_called()
