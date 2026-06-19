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
async def test_workflow_dependency_executes_after_proceed(orchestrator, base_config, mock_intent):
    """After Proceed, messages on the prereq agent must not re-show the prerequisite card."""
    prereq_config = AgentConfig(
        id="prereq-agent",
        name="Prereq Agent",
        persona="I am the prerequisite.",
        greeting="Ready to help with prereqs.",
    )
    request = ConversationRequest(
        conversation_id="conv-1",
        agent_config=base_config,
        messages=[Message(role=MessageRole.USER, content="My router isn't working")],
        completed_workflow_steps=[],
        selected_agent="prereq-agent",
        dependency_configs={"prereq-agent": prereq_config},
    )

    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        with mock.patch.object(
            orchestrator, "_call_llm", return_value="Try rebooting your router."
        ):
            response = await orchestrator.process_message(request)

        assert response.status == ConversationStatus.SUCCESS
        assert "rebooting" in response.reply.content.lower()
        assert "prereq-agent" in response.completed_workflow_steps


@pytest.mark.asyncio
async def test_workflow_dependency_deadlock_guard(orchestrator, base_config, mock_intent):
    """AC #9: If a dependency config cannot be resolved, the handoff must be blocked."""
    request = ConversationRequest(
        conversation_id="conv-1",
        agent_config=base_config,
        messages=[Message(role=MessageRole.USER, content="My router isn't working")],
        completed_workflow_steps=[],
        selected_agent="prereq-agent",
        dependency_configs={},  # MISSING!
    )

    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        with mock.patch.object(orchestrator, "_call_llm", return_value="Staying on target."):
            response = await orchestrator.process_message(request)

            # Should be blocked because of the deadlock guard (unresolvable dependency)
            assert response.status == ConversationStatus.HANDOFF_BLOCKED
            assert response.selected_agent == "target-agent"


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
async def test_workflow_rules_branch_tech_intent_requires_prereq(orchestrator):
    """AC branching: technical intent → workflow block X (prereq); else → no prereq."""
    config = AgentConfig(
        id="router-agent",
        name="Router Agent",
        persona="I route requests.",
        greeting="Hi.",
        workflow_rules=[
            {
                "when": {"agent_name": "technical_support"},
                "dependencies": ["prereq-agent"],
            },
            {"when": {"else": True}, "dependencies": []},
        ],
    )
    tech_intent = IntentResult(
        name="technical_support_request",
        description="d",
        agent_name="technical_support",
        confidence=1.0,
    )
    request = ConversationRequest(
        conversation_id="conv-branch-tech",
        agent_config=config,
        messages=[Message(role=MessageRole.USER, content="My router isn't working")],
        completed_workflow_steps=[],
    )

    with mock.patch.object(orchestrator._intent_router, "detect", return_value=tech_intent):
        response = await orchestrator.process_message(request)

    assert response.status == ConversationStatus.WORKFLOW_CONFIRMATION_REQUIRED
    assert "prereq-agent" in (
        response.confirmation.confirmation_id if response.confirmation else ""
    )


@pytest.mark.asyncio
async def test_workflow_rules_branch_sales_intent_skips_prereq(orchestrator):
    """AC branching: non-technical intent → else branch → no prerequisite card."""
    config = AgentConfig(
        id="router-agent",
        name="Router Agent",
        persona="I route requests.",
        greeting="Hi.",
        workflow_rules=[
            {
                "when": {"agent_name": "technical_support"},
                "dependencies": ["prereq-agent"],
            },
            {"when": {"else": True}, "dependencies": []},
        ],
    )
    sales_intent = IntentResult(
        name="book_service_appointment",
        description="d",
        agent_name="sales",
        confidence=1.0,
    )
    request = ConversationRequest(
        conversation_id="conv-branch-sales",
        agent_config=config,
        messages=[Message(role=MessageRole.USER, content="I want to buy a laptop")],
        completed_workflow_steps=[],
    )

    with mock.patch.object(orchestrator._intent_router, "detect", return_value=sales_intent):
        with mock.patch.object(orchestrator, "_call_llm", return_value="Happy to help you buy."):
            response = await orchestrator.process_message(request)

    assert response.status == ConversationStatus.SUCCESS
    assert response.status != ConversationStatus.WORKFLOW_CONFIRMATION_REQUIRED


@pytest.mark.asyncio
async def test_transitive_workflow_c_before_b_full_flow(orchestrator):
    """Demo 2: A→B only in config, B→C — engine prompts C first, then B, then entry."""
    config_c = AgentConfig(
        id="agent-c",
        name="Step C",
        persona="STEP-C: leaf prerequisite.",
        greeting="g",
    )
    config_b = AgentConfig(
        id="agent-b",
        name="Step B",
        persona="STEP-B: middle prerequisite.",
        greeting="g",
        workflow_dependencies=["agent-c"],
    )
    config_a = AgentConfig(
        id="agent-a",
        name="Step A Entry",
        persona="STEP-A: entry agent.",
        greeting="g",
        workflow_dependencies=["agent-b"],
    )
    deps = {"agent-b": config_b, "agent-c": config_c}
    mock_intent = IntentResult(
        name="book_service_appointment",
        description="d",
        agent_name="sales",
        confidence=1.0,
    )

    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        first = await orchestrator.process_message(
            ConversationRequest(
                conversation_id="conv-transitive",
                agent_config=config_a,
                messages=[Message(role=MessageRole.USER, content="I want to buy something")],
                dependency_configs=deps,
            )
        )

    assert first.status == ConversationStatus.WORKFLOW_CONFIRMATION_REQUIRED
    assert first.confirmation is not None
    assert first.confirmation.confirmation_id == "workflow_agent-c"

    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        confirmed_c = await orchestrator.process_message(
            ConversationRequest(
                conversation_id="conv-transitive",
                agent_config=config_a,
                messages=[Message(role=MessageRole.USER, content="proceed")],
                dependency_configs=deps,
                confirmation_id="workflow_agent-c",
                decision="confirm",
            )
        )

    assert confirmed_c.status == ConversationStatus.SUCCESS
    assert confirmed_c.selected_agent == "agent-c"

    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        with mock.patch.object(
            orchestrator, "_call_llm", return_value="STEP-C: checking inventory."
        ) as llm_mock:
            executed_c = await orchestrator.process_message(
                ConversationRequest(
                    conversation_id="conv-transitive",
                    agent_config=config_a,
                    messages=[Message(role=MessageRole.USER, content="continue")],
                    dependency_configs=deps,
                    selected_agent="agent-c",
                )
            )

    assert executed_c.status == ConversationStatus.SUCCESS
    assert "STEP-C" in executed_c.reply.content
    assert "agent-c" in executed_c.completed_workflow_steps
    llm_mock.assert_called_once()
    system_prompt = llm_mock.call_args[0][0]
    assert "STEP-C:" in system_prompt
    assert "STEP-A:" not in system_prompt

    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        prompt_b = await orchestrator.process_message(
            ConversationRequest(
                conversation_id="conv-transitive",
                agent_config=config_a,
                messages=[Message(role=MessageRole.USER, content="next")],
                dependency_configs=deps,
                selected_agent="agent-c",
                completed_workflow_steps=["agent-c"],
            )
        )

    assert prompt_b.status == ConversationStatus.WORKFLOW_CONFIRMATION_REQUIRED
    assert prompt_b.confirmation is not None
    assert prompt_b.confirmation.confirmation_id == "workflow_agent-b"


@pytest.mark.asyncio
async def test_transitive_workflow_full_chain_c_before_b_before_a(orchestrator):
    """Demo 2 full flow: A->B->C, engine walks C, then B, then A through step 8."""
    config_c = AgentConfig(
        id="agent-c",
        name="Step C",
        persona="STEP-C: leaf prerequisite.",
        greeting="g",
    )
    config_b = AgentConfig(
        id="agent-b",
        name="Step B",
        persona="STEP-B: middle prerequisite.",
        greeting="g",
        workflow_dependencies=["agent-c"],
    )
    config_a = AgentConfig(
        id="agent-a",
        name="Step A Entry",
        persona="STEP-A: entry agent.",
        greeting="g",
        workflow_dependencies=["agent-b"],
    )
    deps = {"agent-b": config_b, "agent-c": config_c}
    mock_intent = IntentResult(
        name="book_service_appointment",
        description="d",
        agent_name="sales",
        confidence=1.0,
    )

    # --- Step 1: First message → prompt for C (transitive) ---
    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        first = await orchestrator.process_message(
            ConversationRequest(
                conversation_id="conv-full-chain",
                agent_config=config_a,
                messages=[Message(role=MessageRole.USER, content="I want to buy something")],
                dependency_configs=deps,
            )
        )

    assert first.status == ConversationStatus.WORKFLOW_CONFIRMATION_REQUIRED
    assert first.confirmation is not None
    assert first.confirmation.confirmation_id == "workflow_agent-c"

    # --- Step 2: Proceed C → selected_agent=agent-c ---
    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        confirmed_c = await orchestrator.process_message(
            ConversationRequest(
                conversation_id="conv-full-chain",
                agent_config=config_a,
                messages=[Message(role=MessageRole.USER, content="proceed")],
                dependency_configs=deps,
                confirmation_id="workflow_agent-c",
                decision="confirm",
            )
        )

    assert confirmed_c.status == ConversationStatus.SUCCESS
    assert confirmed_c.selected_agent == "agent-c"

    # --- Step 3: continue → execute C, system prompt must use STEP-C: persona ---
    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        with mock.patch.object(
            orchestrator, "_call_llm", return_value="STEP-C: checking inventory."
        ) as llm_mock:
            executed_c = await orchestrator.process_message(
                ConversationRequest(
                    conversation_id="conv-full-chain",
                    agent_config=config_a,
                    messages=[Message(role=MessageRole.USER, content="continue")],
                    dependency_configs=deps,
                    selected_agent="agent-c",
                )
            )

    assert executed_c.status == ConversationStatus.SUCCESS
    assert "STEP-C" in executed_c.reply.content
    assert "agent-c" in executed_c.completed_workflow_steps
    system_prompt = llm_mock.call_args[0][0]
    assert "STEP-C:" in system_prompt
    assert "STEP-A:" not in system_prompt

    # --- Step 4: After C done → prompt for B ---
    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        prompt_b = await orchestrator.process_message(
            ConversationRequest(
                conversation_id="conv-full-chain",
                agent_config=config_a,
                messages=[Message(role=MessageRole.USER, content="next")],
                dependency_configs=deps,
                selected_agent="agent-c",
                completed_workflow_steps=["agent-c"],
            )
        )

    assert prompt_b.status == ConversationStatus.WORKFLOW_CONFIRMATION_REQUIRED
    assert prompt_b.confirmation is not None
    assert prompt_b.confirmation.confirmation_id == "workflow_agent-b"
    assert prompt_b.selected_agent == "agent-c"

    # --- Step 5: Proceed B → selected_agent=agent-b ---
    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        confirmed_b = await orchestrator.process_message(
            ConversationRequest(
                conversation_id="conv-full-chain",
                agent_config=config_a,
                messages=[Message(role=MessageRole.USER, content="proceed")],
                dependency_configs=deps,
                confirmation_id="workflow_agent-b",
                decision="confirm",
                selected_agent="agent-c",
                completed_workflow_steps=["agent-c"],
            )
        )

    assert confirmed_b.status == ConversationStatus.SUCCESS
    assert confirmed_b.selected_agent == "agent-b"

    # --- Step 6: continue → execute B, system prompt must use STEP-B: persona ---
    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        with mock.patch.object(
            orchestrator, "_call_llm", return_value="STEP-B: processing request."
        ) as llm_mock:
            executed_b = await orchestrator.process_message(
                ConversationRequest(
                    conversation_id="conv-full-chain",
                    agent_config=config_a,
                    messages=[Message(role=MessageRole.USER, content="continue")],
                    dependency_configs=deps,
                    selected_agent="agent-b",
                    completed_workflow_steps=["agent-c"],
                )
            )

    assert executed_b.status == ConversationStatus.SUCCESS
    assert "STEP-B" in executed_b.reply.content
    assert "agent-b" in executed_b.completed_workflow_steps
    assert "agent-c" in executed_b.completed_workflow_steps
    system_prompt = llm_mock.call_args[0][0]
    assert "STEP-B:" in system_prompt
    assert "STEP-A:" not in system_prompt
    assert "STEP-C:" not in system_prompt

    # --- Step 7: All prereqs done → execute entry agent A ---
    with mock.patch.object(orchestrator._intent_router, "detect", return_value=mock_intent):
        with mock.patch.object(
            orchestrator, "_call_llm", return_value="STEP-A: entry agent responding."
        ) as llm_mock:
            executed_a = await orchestrator.process_message(
                ConversationRequest(
                    conversation_id="conv-full-chain",
                    agent_config=config_a,
                    messages=[Message(role=MessageRole.USER, content="continue")],
                    dependency_configs=deps,
                    selected_agent="agent-b",
                    completed_workflow_steps=["agent-c", "agent-b"],
                )
            )

    assert executed_a.status == ConversationStatus.SUCCESS
    assert "STEP-A" in executed_a.reply.content
    assert executed_a.selected_agent == "agent-a"
    assert executed_a.selected_agent != "general_inquiry"
    system_prompt = llm_mock.call_args[0][0]
    assert "STEP-A:" in system_prompt

    # No more prereq cards — all dependencies satisfied
    remaining_deps = executed_a.completed_workflow_steps or []
    assert "agent-c" in remaining_deps
    assert "agent-b" in remaining_deps


@pytest.mark.asyncio
async def test_transitive_continue_after_proceed_without_locked_intent(orchestrator):
    """Regression: short follow-ups like 'continue' must not trigger clarification."""
    from dataclasses import replace

    from taskorbit.intent import _FALLBACK_RESULT

    config_c = AgentConfig(
        id="agent-c",
        name="Step C",
        persona="STEP-C: leaf prerequisite.",
        greeting="g",
    )
    config_b = AgentConfig(
        id="agent-b",
        name="Step B",
        persona="STEP-B: middle prerequisite.",
        greeting="g",
        workflow_dependencies=["agent-c"],
    )
    config_a = AgentConfig(
        id="agent-a",
        name="Step A Entry",
        persona="STEP-A: entry agent.",
        greeting="g",
        workflow_dependencies=["agent-b"],
    )
    deps = {"agent-b": config_b, "agent-c": config_c}
    mock_intent = IntentResult(
        name="book_service_appointment",
        description="d",
        agent_name="sales",
        confidence=1.0,
    )

    async def detect_side_effect(prompt, *args, **kwargs):
        if prompt.strip().lower() == "continue":
            return replace(_FALLBACK_RESULT, confidence=0.2, requires_clarification=True)
        return mock_intent

    with mock.patch.object(orchestrator._intent_router, "detect", side_effect=detect_side_effect):
        first = await orchestrator.process_message(
            ConversationRequest(
                conversation_id="conv-transitive-continue",
                agent_config=config_a,
                messages=[Message(role=MessageRole.USER, content="I want to buy something")],
                dependency_configs=deps,
            )
        )

    assert first.status == ConversationStatus.WORKFLOW_CONFIRMATION_REQUIRED
    assert first.locked_intent_name == mock_intent.name

    with mock.patch.object(orchestrator._intent_router, "detect", side_effect=detect_side_effect):
        confirmed_c = await orchestrator.process_message(
            ConversationRequest(
                conversation_id="conv-transitive-continue",
                agent_config=config_a,
                messages=[Message(role=MessageRole.USER, content="proceed")],
                dependency_configs=deps,
                confirmation_id="workflow_agent-c",
                decision="confirm",
                current_intent_name=mock_intent.name,
            )
        )

    assert confirmed_c.selected_agent == "agent-c"
    assert confirmed_c.locked_intent_name == mock_intent.name

    with mock.patch.object(orchestrator._intent_router, "detect", side_effect=detect_side_effect):
        with mock.patch.object(
            orchestrator, "_call_llm", return_value="STEP-C: checking inventory."
        ):
            executed_c = await orchestrator.process_message(
                ConversationRequest(
                    conversation_id="conv-transitive-continue",
                    agent_config=config_a,
                    messages=[Message(role=MessageRole.USER, content="continue")],
                    dependency_configs=deps,
                    selected_agent="agent-c",
                )
            )

    assert executed_c.status == ConversationStatus.SUCCESS
    assert executed_c.status != ConversationStatus.CLARIFICATION
    assert "STEP-C" in executed_c.reply.content
    assert "agent-c" in executed_c.completed_workflow_steps


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
