"""Unit tests for workflow_rules resolution."""

from taskorbit.types import AgentConfig, WorkflowRule, WorkflowRuleWhen
from taskorbit.workflow_rules import collect_workflow_dependency_ids, resolve_workflow_dependencies


def test_collect_workflow_dependency_ids_unions_static_and_rules() -> None:
    config = AgentConfig(
        id="entry",
        name="Entry",
        persona="p",
        greeting="g",
        workflow_dependencies=["static-dep"],
        workflow_rules=[
            WorkflowRule(
                when=WorkflowRuleWhen(intent="technical_support_request"),
                dependencies=["tech-dep"],
            ),
            WorkflowRule(when=WorkflowRuleWhen(else_branch=True), dependencies=[]),
        ],
    )
    ids = collect_workflow_dependency_ids(config)
    assert set(ids) == {"static-dep", "tech-dep"}


def test_resolve_uses_tech_branch_when_intent_matches() -> None:
    config = AgentConfig(
        id="router-agent",
        name="Router",
        persona="p",
        greeting="g",
        workflow_rules=[
            WorkflowRule(
                when=WorkflowRuleWhen(agent_name="technical_support"),
                dependencies=["technical-support-agent-demos"],
            ),
            WorkflowRule(when=WorkflowRuleWhen(else_branch=True), dependencies=[]),
        ],
    )
    deps = resolve_workflow_dependencies(
        config,
        intent_name="technical_support_request",
        intent_agent_name="technical_support",
    )
    assert deps == ["technical-support-agent-demos"]


def test_resolve_uses_else_branch_for_sales_intent() -> None:
    config = AgentConfig(
        id="router-agent",
        name="Router",
        persona="p",
        greeting="g",
        workflow_rules=[
            WorkflowRule(
                when=WorkflowRuleWhen(agent_name="technical_support"),
                dependencies=["technical-support-agent-demos"],
            ),
            WorkflowRule(when=WorkflowRuleWhen(else_branch=True), dependencies=[]),
        ],
    )
    deps = resolve_workflow_dependencies(
        config,
        intent_name="book_service_appointment",
        intent_agent_name="sales",
    )
    assert deps == []


def test_resolve_falls_back_to_static_dependencies_without_rules() -> None:
    config = AgentConfig(
        id="sales2-agent",
        name="Sales",
        persona="p",
        greeting="g",
        workflow_dependencies=["technical-support-agent-demos"],
    )
    deps = resolve_workflow_dependencies(
        config,
        intent_name="book_service_appointment",
        intent_agent_name="sales",
    )
    assert deps == ["technical-support-agent-demos"]


def test_agent_config_rejects_else_branch_not_last() -> None:
    import pytest

    with pytest.raises(ValueError, match="else_branch rule must be the last"):
        AgentConfig(
            id="router-agent",
            name="Router",
            persona="p",
            greeting="g",
            workflow_rules=[
                WorkflowRule(when=WorkflowRuleWhen(else_branch=True), dependencies=[]),
                WorkflowRule(
                    when=WorkflowRuleWhen(intent="technical_support_request"),
                    dependencies=["tech-dep"],
                ),
            ],
        )
