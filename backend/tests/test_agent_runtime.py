"""Unit tests for the basic agent runtime (issue #33).

Tests cover: MockIntentDetector, AgentRegistry routing,
ConversationOrchestrator happy path, and error handling.

Run with: poetry run pytest
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from taskorbit.agents import (
    AgentRegistry,
    AppointmentManagementAgent,
    GeneralInquiryAgent,
    SalesAgent,
    TechnicalSupportAgent,
)
from taskorbit.intent import MockIntentDetector
from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import (
    AgentConfig,
    ConversationRequest,
    Message,
    MessageRole,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(agent_id: str = "sales-agent", name: str = "Test Agent") -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        name=name,
        persona="Helpful assistant for testing.",
        greeting="Hello, how can I help?",
    )


def _make_request(
    agent_id: str = "sales-agent",
    message: str = "I need help",
    conversation_id: str = "conv-test-1",
) -> ConversationRequest:
    return ConversationRequest(
        conversation_id=conversation_id,
        agent_config=_make_config(agent_id),
        messages=[Message(role=MessageRole.USER, content=message)],
    )


# ---------------------------------------------------------------------------
# MockIntentDetector
# ---------------------------------------------------------------------------


def test_mock_intent_always_returns_book_service_appointment() -> None:
    detector = MockIntentDetector()
    result = detector.detect("I want to book a plumber")
    assert result.name == "book_service_appointment"


def test_mock_intent_ignores_prompt_content() -> None:
    detector = MockIntentDetector()
    assert (
        detector.detect("anything").name == detector.detect("something completely different").name
    )


def test_mock_intent_result_has_required_inputs() -> None:
    result = MockIntentDetector().detect("hello")
    assert any(i["name"] == "caller_name" for i in result.required_inputs)
    assert any(i["name"] == "phone_number" for i in result.required_inputs)
    assert any(i["name"] == "preferred_date" for i in result.required_inputs)


def test_mock_intent_result_has_workflow_steps() -> None:
    result = MockIntentDetector().detect("hello")
    assert len(result.workflow_steps) > 0
    step_ids = [s["id"] for s in result.workflow_steps]
    assert "greet" in step_ids
    assert "end" in step_ids


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------


def test_registry_returns_generic_agent_by_default() -> None:
    config = _make_config("generic-agent")
    agent = AgentRegistry.get_agent(config, ConversationOrchestrator())
    # AC #71: Now returns GenericAgent instead of SalesAgent for unknown IDs
    from taskorbit.agents import GenericAgent

    assert isinstance(agent, GenericAgent)
    assert agent.agent_name == "generic-agent"


def test_registry_returns_sales_agent_for_sales_id() -> None:
    config = _make_config("sales-id")
    agent = AgentRegistry.create(config, ConversationOrchestrator())
    assert isinstance(agent, SalesAgent)


def test_registry_returns_technical_support_agent_for_support_id() -> None:
    config = _make_config("technical-support-bot")
    agent = AgentRegistry.get_agent(config, ConversationOrchestrator())
    assert isinstance(agent, TechnicalSupportAgent)


def test_registry_returns_technical_support_agent_for_tech_prefix() -> None:
    config = _make_config("tech-helpdesk")
    agent = AgentRegistry.get_agent(config, ConversationOrchestrator())
    assert isinstance(agent, TechnicalSupportAgent)


def test_registry_agent_carries_config() -> None:
    config = _make_config("sales-agent", name="My Agent")
    agent = AgentRegistry.get_agent(config, ConversationOrchestrator())
    assert agent.config.name == "My Agent"


# ---------------------------------------------------------------------------
# ConversationOrchestrator — happy path
# ---------------------------------------------------------------------------


@patch.object(ConversationOrchestrator, "_call_llm", new_callable=AsyncMock)
async def test_process_message_returns_success_status(
    mock_llm: AsyncMock, mock_good_intent: object
) -> None:
    mock_llm.return_value = "[Mocked LLM] Hello"
    response = await ConversationOrchestrator().process_message(_make_request())
    assert response.status == "success"


@patch.object(ConversationOrchestrator, "_call_llm", new_callable=AsyncMock)
async def test_process_message_sets_selected_intent(
    mock_llm: AsyncMock, mock_good_intent: object
) -> None:
    mock_llm.return_value = "[Mocked LLM] Hello"
    response = await ConversationOrchestrator().process_message(_make_request())
    assert response.selected_intent == "book_service_appointment"


@patch.object(ConversationOrchestrator, "_call_llm", new_callable=AsyncMock)
async def test_process_message_sets_selected_agent_name(
    mock_llm: AsyncMock, mock_good_intent: object
) -> None:
    mock_llm.return_value = "[Mocked LLM] Hello"
    response = await ConversationOrchestrator().process_message(_make_request())
    # selected_agent now reflects the routed agent_name, not the config display name
    assert response.selected_agent in (
        "sales",
        "technical_support",
        "general_inquiry",
        "appointment_management",
        "customer_dissatisfaction",
    )


@patch.object(ConversationOrchestrator, "_call_llm", new_callable=AsyncMock)
async def test_process_message_reply_contains_mocked_llm_marker(
    mock_llm: AsyncMock, mock_good_intent: object
) -> None:
    mock_llm.return_value = "[Mocked LLM] Hello"
    response = await ConversationOrchestrator().process_message(
        _make_request(message="Hello there")
    )
    assert "[Mocked LLM]" in response.reply.content


@patch.object(ConversationOrchestrator, "_call_llm", new_callable=AsyncMock)
async def test_process_message_preserves_conversation_id(
    mock_llm: AsyncMock, mock_good_intent: object
) -> None:
    mock_llm.return_value = "[Mocked LLM] Hello"
    request = _make_request(conversation_id="conv-abc-123")
    response = await ConversationOrchestrator().process_message(request)
    assert response.conversation_id == "conv-abc-123"


@patch.object(ConversationOrchestrator, "_call_llm", new_callable=AsyncMock)
async def test_process_message_reply_role_is_assistant(
    mock_llm: AsyncMock, mock_good_intent: object
) -> None:
    mock_llm.return_value = "[Mocked LLM] Hello"
    response = await ConversationOrchestrator().process_message(_make_request())
    assert response.reply.role == MessageRole.ASSISTANT


# ---------------------------------------------------------------------------
# ConversationOrchestrator — error handling
# ---------------------------------------------------------------------------


async def test_process_message_no_user_message_returns_error() -> None:
    request = ConversationRequest(
        conversation_id="conv-err-1",
        agent_config=_make_config(),
        messages=[],
    )
    response = await ConversationOrchestrator().process_message(request)
    assert response.status == "error"
    assert response.error != ""


async def test_process_message_error_response_has_conversation_id() -> None:
    request = ConversationRequest(
        conversation_id="conv-err-2",
        agent_config=_make_config(),
        messages=[],
    )
    response = await ConversationOrchestrator().process_message(request)
    assert response.conversation_id == "conv-err-2"


async def test_process_message_error_reply_is_user_friendly() -> None:
    request = ConversationRequest(
        conversation_id="conv-err-3",
        agent_config=_make_config(),
        messages=[],
    )
    response = await ConversationOrchestrator().process_message(request)
    assert len(response.reply.content) > 0


async def test_process_message_empty_content_returns_error() -> None:
    request = ConversationRequest(
        conversation_id="conv-err-4",
        agent_config=_make_config(),
        messages=[Message(role=MessageRole.USER, content="   ")],
    )
    response = await ConversationOrchestrator().process_message(request)
    assert response.status == "error"


# ---------------------------------------------------------------------------
# AgentRegistry — GeneralInquiryAgent
# ---------------------------------------------------------------------------


def test_registry_returns_general_inquiry_agent_for_inquiry_id() -> None:
    config = _make_config("general-inquiry-bot")
    agent = AgentRegistry.create(config, ConversationOrchestrator())
    assert isinstance(agent, GeneralInquiryAgent)


def test_registry_returns_general_inquiry_agent_for_faq_id() -> None:
    config = _make_config("faq-agent")
    agent = AgentRegistry.create(config, ConversationOrchestrator())
    assert isinstance(agent, GeneralInquiryAgent)


def test_registry_returns_general_inquiry_agent_for_general_id() -> None:
    config = _make_config("general-assistant")
    agent = AgentRegistry.create(config, ConversationOrchestrator())
    assert isinstance(agent, GeneralInquiryAgent)


def test_general_inquiry_agent_name() -> None:
    config = _make_config("general-inquiry-bot")
    agent = AgentRegistry.create(config, ConversationOrchestrator())
    assert agent.agent_name == "general_inquiry"


def test_general_inquiry_agent_returns_config_tools() -> None:
    config = _make_config("general-inquiry-bot")
    agent = AgentRegistry.create(config, ConversationOrchestrator())
    assert agent.get_task_definitions() == config.tools


# ---------------------------------------------------------------------------
# AgentRegistry — AppointmentManagementAgent
# ---------------------------------------------------------------------------


def test_registry_returns_appointment_agent_for_appointment_id() -> None:
    config = _make_config("appointment-manager")
    agent = AgentRegistry.create(config, ConversationOrchestrator())
    assert isinstance(agent, AppointmentManagementAgent)


def test_registry_returns_appointment_agent_for_reschedule_id() -> None:
    config = _make_config("reschedule-bot")
    agent = AgentRegistry.create(config, ConversationOrchestrator())
    assert isinstance(agent, AppointmentManagementAgent)


def test_registry_returns_appointment_agent_for_cancel_id() -> None:
    config = _make_config("cancel-booking-agent")
    agent = AgentRegistry.create(config, ConversationOrchestrator())
    assert isinstance(agent, AppointmentManagementAgent)


def test_registry_returns_appointment_agent_for_booking_id() -> None:
    config = _make_config("booking-management")
    agent = AgentRegistry.create(config, ConversationOrchestrator())
    assert isinstance(agent, AppointmentManagementAgent)


def test_appointment_agent_name() -> None:
    config = _make_config("appointment-manager")
    agent = AgentRegistry.create(config, ConversationOrchestrator())
    assert agent.agent_name == "appointment_management"


def test_appointment_agent_returns_config_tools() -> None:
    config = _make_config("appointment-manager")
    agent = AgentRegistry.create(config, ConversationOrchestrator())
    assert agent.get_task_definitions() == config.tools


# ---------------------------------------------------------------------------
# AgentRegistry — create() vs get_agent() consistency
# ---------------------------------------------------------------------------


def test_create_and_get_agent_return_same_type() -> None:
    config = _make_config("technical-support-bot")
    orchestrator = ConversationOrchestrator()
    assert type(AgentRegistry.create(config, orchestrator)) is type(
        AgentRegistry.get_agent(config, orchestrator)
    )


def test_registry_default_falls_back_to_generic_agent() -> None:
    config = _make_config("unknown-xyz-agent")
    agent = AgentRegistry.create(config, ConversationOrchestrator())
    from taskorbit.agents import GenericAgent

    assert isinstance(agent, GenericAgent)
    assert agent.agent_name == "unknown-xyz-agent"
