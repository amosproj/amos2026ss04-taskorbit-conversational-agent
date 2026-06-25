"""Unit tests for workflow helper functions in orchestration."""

from dataclasses import replace

from taskorbit.intent import _FALLBACK_RESULT, IntentResult
from taskorbit.orchestration import (
    _effective_selected_agent,
    _resolve_intent_after_clarification_gate,
)
from taskorbit.types import AgentConfig, ConversationRequest, Message, MessageRole


def test_effective_selected_agent_none() -> None:
    assert _effective_selected_agent(None) is None


def test_effective_selected_agent_empty_string() -> None:
    assert _effective_selected_agent("") is None


def test_effective_selected_agent_whitespace_only() -> None:
    assert _effective_selected_agent("  ") is None


def test_effective_selected_agent_strips_value() -> None:
    assert _effective_selected_agent(" agent-a ") == "agent-a"


def test_resolve_intent_after_clarification_gate_passthrough_when_not_clarifying() -> None:
    intent = IntentResult(
        name="book_service_appointment",
        description="d",
        agent_name="sales",
        confidence=1.0,
    )
    request = ConversationRequest(
        conversation_id="conv-gate",
        agent_config=AgentConfig(id="agent-a", name="A", persona="p", greeting="g"),
        messages=[Message(role=MessageRole.USER, content="hello")],
    )
    assert _resolve_intent_after_clarification_gate(request, intent) is intent


def test_resolve_intent_after_clarification_gate_bypasses_during_workflow_prereq() -> None:
    config_c = AgentConfig(id="agent-c", name="C", persona="p", greeting="g")
    config_b = AgentConfig(
        id="agent-b",
        name="B",
        persona="p",
        greeting="g",
        workflow_dependencies=["agent-c"],
    )
    config_a = AgentConfig(
        id="agent-a",
        name="A",
        persona="p",
        greeting="g",
        workflow_dependencies=["agent-b"],
    )
    request = ConversationRequest(
        conversation_id="conv-gate",
        agent_config=config_a,
        messages=[Message(role=MessageRole.USER, content="continue")],
        selected_agent="agent-c",
        dependency_configs={"agent-b": config_b, "agent-c": config_c},
        completed_workflow_steps=[],
    )
    low_conf = replace(_FALLBACK_RESULT, confidence=0.2, requires_clarification=True)

    resolved = _resolve_intent_after_clarification_gate(request, low_conf)

    assert resolved.requires_clarification is False
    assert resolved.confidence == 1.0


def test_resolve_intent_after_clarification_gate_keeps_clarification_outside_workflow() -> None:
    low_conf = replace(_FALLBACK_RESULT, confidence=0.2, requires_clarification=True)
    request = ConversationRequest(
        conversation_id="conv-gate",
        agent_config=AgentConfig(id="agent-a", name="A", persona="p", greeting="g"),
        messages=[Message(role=MessageRole.USER, content="umm")],
    )

    resolved = _resolve_intent_after_clarification_gate(request, low_conf)

    assert resolved.requires_clarification is True
