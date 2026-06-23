"""Unit tests for workflow_rules resolution."""

from taskorbit.types import AgentConfig, WorkflowRule, WorkflowRuleWhen
from taskorbit.workflow_rules import (
    collect_workflow_dependency_ids,
    expand_workflow_dependencies,
    resolve_workflow_dependencies,
)


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


# ---------------------------------------------------------------------------
# expand_workflow_dependencies
# ---------------------------------------------------------------------------


def _make_agent(
    agent_id: str, *, static: list[str] | None = None, rules: list[WorkflowRule] | None = None
) -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        name=agent_id,
        persona="p",
        greeting="g",
        workflow_dependencies=static or [],
        workflow_rules=rules or [],
    )


def test_expand_includes_static_deps_of_intermediate_agent() -> None:
    """Intermediate agent's static workflow_dependencies are transitively expanded."""
    dep_b = _make_agent("dep-b")
    dep_a = _make_agent("dep-a", static=["dep-b"])

    expanded = expand_workflow_dependencies(["dep-a"], {"dep-a": dep_a, "dep-b": dep_b})
    assert expanded == ["dep-b", "dep-a"]


def test_expand_includes_rule_based_deps_of_intermediate_agent() -> None:
    """Intermediate agent's workflow_rules dependency IDs are transitively expanded.

    Previously only config.workflow_dependencies was traversed, so a prerequisite
    declared only in a workflow_rule branch would be silently skipped.
    """
    dep_b = _make_agent("dep-b")
    dep_a = _make_agent(
        "dep-a",
        rules=[
            WorkflowRule(
                when=WorkflowRuleWhen(intent="some_intent"),
                dependencies=["dep-b"],
            )
        ],
    )

    expanded = expand_workflow_dependencies(["dep-a"], {"dep-a": dep_a, "dep-b": dep_b})
    assert "dep-b" in expanded
    assert expanded.index("dep-b") < expanded.index("dep-a")


def test_expand_cycle_guard_prevents_infinite_loop() -> None:
    """Cyclic deps (A → B → A) terminate without infinite recursion."""
    dep_a = _make_agent("dep-a", static=["dep-b"])
    dep_b = _make_agent("dep-b", static=["dep-a"])

    expanded = expand_workflow_dependencies(["dep-a"], {"dep-a": dep_a, "dep-b": dep_b})
    assert set(expanded) == {"dep-a", "dep-b"}


def test_agent_config_rejects_multiple_else_branch_rules() -> None:
    import pytest

    with pytest.raises(ValueError, match="only one else_branch rule is allowed"):
        AgentConfig(
            id="router-agent",
            name="Router",
            persona="p",
            greeting="g",
            workflow_rules=[
                WorkflowRule(
                    when=WorkflowRuleWhen(intent="technical_support_request"),
                    dependencies=["tech-dep"],
                ),
                WorkflowRule(when=WorkflowRuleWhen(else_branch=True), dependencies=[]),
                WorkflowRule(when=WorkflowRuleWhen(else_branch=True), dependencies=["other-dep"]),
            ],
        )
