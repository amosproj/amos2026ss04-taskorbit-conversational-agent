"""Tests for transitive workflow dependency resolution."""

from taskorbit.types import AgentConfig
from taskorbit.workflow_rules import expand_workflow_dependencies

def test_expand_workflow_dependencies_linear() -> None:
    # A -> B -> C
    config_c = AgentConfig(id="agent-c", name="C", persona="p", greeting="g")
    config_b = AgentConfig(
        id="agent-b", 
        name="B", 
        persona="p", 
        greeting="g", 
        workflow_dependencies=["agent-c"]
    )
    
    dependency_configs = {
        "agent-b": config_b,
        "agent-c": config_c
    }
    
    # If we depend on B, we should get [C, B]
    expanded = expand_workflow_dependencies(["agent-b"], dependency_configs)
    assert expanded == ["agent-c", "agent-b"]

def test_expand_workflow_dependencies_diamond() -> None:
    # A -> [B, C], B -> D, C -> D
    config_d = AgentConfig(id="agent-d", name="D", persona="p", greeting="g")
    config_c = AgentConfig(
        id="agent-c", name="C", persona="p", greeting="g", workflow_dependencies=["agent-d"]
    )
    config_b = AgentConfig(
        id="agent-b", name="B", persona="p", greeting="g", workflow_dependencies=["agent-d"]
    )
    
    dependency_configs = {
        "agent-b": config_b,
        "agent-c": config_c,
        "agent-d": config_d
    }
    
    expanded = expand_workflow_dependencies(["agent-b", "agent-c"], dependency_configs)
    # Expected: D (prereq of B), B, C (D already seen)
    assert expanded == ["agent-d", "agent-b", "agent-c"]

def test_expand_workflow_dependencies_cycle_safety() -> None:
    # A -> B, B -> A (should not infinite loop)
    config_a = AgentConfig(id="agent-a", name="A", persona="p", greeting="g", workflow_dependencies=["agent-b"])
    config_b = AgentConfig(id="agent-b", name="B", persona="p", greeting="g", workflow_dependencies=["agent-a"])
    
    dependency_configs = {
        "agent-a": config_a,
        "agent-b": config_b
    }
    
    expanded = expand_workflow_dependencies(["agent-a"], dependency_configs)
    # Just ensure it terminates and contains both
    assert set(expanded) == {"agent-a", "agent-b"}
