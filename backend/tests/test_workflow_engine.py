"""Tests for the Conditional Workflow Engine (Issue #71)."""

import pytest
import unittest.mock as mock
from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import (
    AgentConfig,
    ConversationRequest,
    ConversationStatus,
    Message,
    MessageRole,
)
from taskorbit.intent import IntentResult

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
        completed_workflow_steps=[], # Prereq missing
    )
    
    with mock.patch.object(orchestrator._intent_router, 'detect', return_value=mock_intent):
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
    
    with mock.patch.object(orchestrator._intent_router, 'detect', return_value=mock_intent):
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
        completed_workflow_steps=["prereq-agent"], # Prereq satisfied
    )
    
    # Mock LLM call as well because it proceeds to LLM turn
    with mock.patch.object(orchestrator._intent_router, 'detect', return_value=mock_intent):
        with mock.patch.object(orchestrator, '_call_llm', return_value="Proceeding with target agent."):
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
        allowed_handoffs=["agent-b"], # Only B allowed
    )
    
    request = ConversationRequest(
        conversation_id="conv-1",
        agent_config=config,
        selected_agent="sales", # current agent name
        current_intent_name="book_service_appointment", # current intent
        messages=[Message(role=MessageRole.USER, content="Transfer me to Agent C")], # Agent C not allowed
    )
    
    handoff_intent = IntentResult(name="intent_c", description="d", agent_name="agent_c", confidence=1.0)
    
    with mock.patch.object(orchestrator._intent_router, 'detect', return_value=handoff_intent):
        with mock.patch.object(orchestrator, '_call_llm', return_value="Staying on A."):
            response = await orchestrator.process_message(request)
            
            # Should have stayed on "sales" because Agent C is not in allowed_handoffs
            assert response.selected_agent != "agent_c"
            assert response.selected_agent == "sales"
