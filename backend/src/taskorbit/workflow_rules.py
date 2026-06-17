"""Conditional workflow rule evaluation (Issue #71 branching AC)."""

from __future__ import annotations

from taskorbit.logging.setup import get_logger
from taskorbit.types import AgentConfig, WorkflowRule

logger = get_logger(__name__)


def collect_workflow_dependency_ids(config: AgentConfig) -> list[str]:
    """Union of static deps and every branch listed in workflow_rules."""
    ids: set[str] = set(config.workflow_dependencies or [])
    for rule in config.workflow_rules or []:
        ids.update(rule.dependencies)
    return list(ids)


def resolve_workflow_dependencies(
    config: AgentConfig,
    *,
    intent_name: str,
    intent_agent_name: str,
) -> list[str]:
    """Pick workflow block ids for this turn from rules, else static workflow_dependencies.

    Rules are evaluated in order; the first match wins. A rule with ``when.else``
    runs only when no earlier rule matched. If nothing matches and there is no
    else branch, fall back to ``workflow_dependencies``.
    """
    if not config.workflow_rules:
        return list(config.workflow_dependencies)

    matched = False
    for rule in config.workflow_rules:
        if _rule_matches(
            rule, intent_name=intent_name, intent_agent_name=intent_agent_name, matched=matched
        ):
            if rule.when.else_branch:
                logger.info(
                    "workflow_rule_else_matched",
                    agent_id=config.id,
                    dependencies=rule.dependencies,
                )
            else:
                matched = True
                logger.info(
                    "workflow_rule_matched",
                    agent_id=config.id,
                    intent=intent_name,
                    intent_agent=intent_agent_name,
                    dependencies=rule.dependencies,
                )
            return list(rule.dependencies)

    return list(config.workflow_dependencies)


def expand_workflow_dependencies(
    dependency_ids: list[str],
    dependency_configs: dict[str, AgentConfig],
) -> list[str]:
    """Recursively expand a list of dependencies to include their own prerequisites.

    Returns an ordered list where prerequisites appear before the agents that
    depend on them (topological sort). Cycles are ignored (first-come first-served).
    """
    result: list[str] = []
    seen: set[str] = set()

    def visit(agent_id: str) -> None:
        if agent_id in seen:
            return
        seen.add(agent_id)

        config = dependency_configs.get(agent_id)
        if config:
            # Recursively visit children (prerequisites) first
            # Note: We only expand static dependencies here as branching rules
            # are intent-dependent and only evaluated for the active entry agent.
            for prereq_id in config.workflow_dependencies:
                visit(prereq_id)

        result.append(agent_id)

    for dep_id in dependency_ids:
        visit(dep_id)

    return result


def _rule_matches(
    rule: WorkflowRule,
    *,
    intent_name: str,
    intent_agent_name: str,
    matched: bool,
) -> bool:
    when = rule.when
    if when.else_branch:
        return not matched

    if when.intent is None and when.agent_name is None:
        return False

    if when.intent is not None and when.intent != intent_name:
        return False
    if when.agent_name is not None and when.agent_name != intent_agent_name:
        return False
    return True
