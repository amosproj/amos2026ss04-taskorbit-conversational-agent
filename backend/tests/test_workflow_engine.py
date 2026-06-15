"""Tests for the Conditional Workflow Engine (Issue #71)."""

import unittest.mock as mock

import pytest

from taskorbit.intent import IntentResult
from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import (
    AgentConfig,
    ConversationRequest,
    ConversationStatus,
    Message,
    MessageRole,
)


@pytest.fixture
def orchestrator():
    return ConversationOrchestrator()


@pytest.fixture
def base_config():
    return AgentConfig(
        id="target-agent",
        name="Target Agent",
        persona="I am the target.",
        greeting="Target ready.",
        workflow_dependencies=["prereq-agent"],
        allowed_handoffs=["handoff-agent"],
    )


@pytest.fixture
def mock_intent():
    return IntentResult(name="target_intent", description="d", agent_name="sales", confidence=1.0)


@pytest.mark.asyncio
async def test_workflow_dependency_triggers_confirmation(orchestrator, base_config, mock_intent):
    request = ConversationRequest(
        conversation_id="conv-1",
        agent_config=base_config,
        messages=[Message(role=MessageRole.USER, content="I want to use the target agent.")],
        completed_workflow_steps=[],  # Prereq missing
    )

    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        response = await orchestrator.process_message(request)

        assert response.status == ConversationStatus.WORKFLOW_CONFIRMATION_REQUIRED
        assert response.confirmation is not None
        assert "prereq-agent" in response.confirmation.confirmation_id
        assert "prereq agent" in response.reply.content.lower()


@pytest.mark.asyncio
async def test_workflow_dependency_confirmed_switches_agent(orchestrator, base_config, mock_intent):
    request = ConversationRequest(
        conversation_id="conv-1",
        agent_config=base_config,
        messages=[Message(role=MessageRole.USER, content="Yes, proceed.")],
        completed_workflow_steps=[],
        confirmation_id="workflow_prereq-agent",
        decision="confirm",
    )

    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        response = await orchestrator.process_message(request)

        assert response.status == ConversationStatus.SUCCESS
        assert response.selected_agent == "prereq-agent"
        assert "prereq agent" in response.reply.content.lower()


@pytest.mark.asyncio
async def test_workflow_dependency_satisfied_proceeds(orchestrator, base_config, mock_intent):
    request = ConversationRequest(
        conversation_id="conv-1",
        agent_config=base_config,
        messages=[Message(role=MessageRole.USER, content="Now use the target.")],
        completed_workflow_steps=["prereq-agent"],  # Prereq satisfied
    )

    # Mock LLM call as well because it proceeds to LLM turn
    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        with mock.patch.object(
            orchestrator, "_call_llm", return_value="Proceeding with target agent."
        ):
            response = await orchestrator.process_message(request)

            # Should proceed to normal agent execution
            assert response.status == ConversationStatus.SUCCESS
            assert response.selected_agent != "prereq-agent"


@pytest.mark.asyncio
async def test_handoff_blocked_if_not_allowed(orchestrator):
    config = AgentConfig(
        id="agent-a",
        name="Agent A",
        persona="Agent A persona",
        greeting="Hi",
        allowed_handoffs=["agent-b"],  # Only B allowed
    )

    request = ConversationRequest(
        conversation_id="conv-1",
        agent_config=config,
        selected_agent="sales",  # current agent name
        current_intent_name="book_service_appointment",  # current intent
        messages=[
            Message(role=MessageRole.USER, content="Transfer me to Agent C")
        ],  # Agent C not allowed
    )

    handoff_intent = IntentResult(
        name="intent_c", description="d", agent_name="technical_support", confidence=1.0
    )

    with mock.patch.object(orchestrator._intent_router, "detect", return_value=handoff_intent):
        with mock.patch.object(orchestrator, "_call_llm", return_value="Staying on A."):
            response = await orchestrator.process_message(request)

            # Should be blocked
            assert response.status == ConversationStatus.HANDOFF_BLOCKED
            assert response.selected_agent == "sales"
            assert "only able to help you with the current topic" in response.reply.content


@pytest.mark.asyncio
async def test_turn_1_entry_agent_locked(orchestrator):
    # Config says Sales
    config = AgentConfig(
        id="sales-agent",
        name="Sales",
        persona="p",
        greeting="g",
    )

    # Intent says Technical Support
    tech_intent = IntentResult(
        name="t", description="d", agent_name="technical_support", confidence=1.0
    )

    request = ConversationRequest(
        conversation_id="conv-1",
        agent_config=config,
        messages=[Message(role=MessageRole.USER, content="Tech help please")],
        selected_agent=None,  # Turn 1
    )

    with mock.patch.object(orchestrator._intent_router, "detect", return_value=tech_intent):
        with mock.patch.object(orchestrator, "_call_llm", return_value="Hi from Sales"):
            response = await orchestrator.process_message(request)

            # Should be locked to Sales because it's Turn 1
            assert response.selected_agent == "sales"


@pytest.mark.asyncio
async def test_handoff_allowed_via_mapping(orchestrator):
    config = AgentConfig(
        id="agent-a",
        name="Agent A",
        persona="p",
        greeting="g",
        allowed_handoffs=["support-agent"],  # Mapping 'support-agent' -> 'technical_support'
    )

    request = ConversationRequest(
        conversation_id="conv-1",
        agent_config=config,
        selected_agent="sales",
        messages=[Message(role=MessageRole.USER, content="Transfer to tech")],
    )

    tech_intent = IntentResult(
        name="t", description="d", agent_name="technical_support", confidence=1.0
    )

    with mock.patch.object(orchestrator._intent_router, "detect", return_value=tech_intent):
        with mock.patch.object(orchestrator, "_call_llm", return_value="Transferring to tech"):
            response = await orchestrator.process_message(request)

            # Should be allowed because 'support-agent' maps to 'technical_support'
            assert response.status == ConversationStatus.SUCCESS
            assert response.selected_agent == "technical_support"
