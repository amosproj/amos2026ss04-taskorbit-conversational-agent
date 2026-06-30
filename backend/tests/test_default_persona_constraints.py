"""Default persona-constraints applied at agent creation (#168).

A brand-new / blank agent must never be unguarded: a config saved without
persona_constraints gets a sensible default, while a creator's own constraints
(even a partial one) are preserved untouched.
"""

from __future__ import annotations

from taskorbit.database.crud import _ensure_persona_constraints
from taskorbit.types import default_persona_constraints


def test_default_persona_constraints_shape() -> None:
    pc = default_persona_constraints()
    assert pc.scope
    assert pc.refusal_template
    assert "recipes" in pc.out_of_scope


def test_ensure_injects_default_when_absent() -> None:
    config = {"id": "a1", "name": "Auto Car Salesman", "persona": "A dealership rep."}
    out = _ensure_persona_constraints(config)
    pc = out["persona_constraints"]
    assert pc["scope"]
    assert pc["refusal_template"]
    assert "recipes" in pc["out_of_scope"]
    # original config object is not mutated (a new dict is returned)
    assert "persona_constraints" not in config


def test_ensure_injects_default_when_block_is_empty() -> None:
    config = {
        "name": "X",
        "persona_constraints": {"scope": None, "out_of_scope": [], "refusal_template": None},
    }
    out = _ensure_persona_constraints(config)
    assert out["persona_constraints"]["scope"]
    assert "recipes" in out["persona_constraints"]["out_of_scope"]


def test_ensure_preserves_creator_constraints() -> None:
    config = {
        "name": "Car Salesman",
        "persona_constraints": {
            "scope": "Car sales only",
            "out_of_scope": ["pizza"],
            "refusal_template": "I only do car sales.",
        },
    }
    out = _ensure_persona_constraints(config)
    assert out["persona_constraints"]["scope"] == "Car sales only"
    assert out["persona_constraints"]["out_of_scope"] == ["pizza"]


def test_ensure_preserves_partial_creator_constraints() -> None:
    """A creator who set only a scope keeps it; we do not override partial config."""
    config = {
        "name": "X",
        "persona_constraints": {
            "scope": "Just support",
            "out_of_scope": [],
            "refusal_template": None,
        },
    }
    out = _ensure_persona_constraints(config)
    assert out["persona_constraints"]["scope"] == "Just support"
    assert out["persona_constraints"]["out_of_scope"] == []
