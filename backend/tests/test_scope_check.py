"""Unit tests for the lightweight pre-LLM scope classifier."""
from __future__ import annotations

from taskorbit.types import PersonaConstraints
from taskorbit.integrations.llm.scope_check import is_message_in_scope


def test_no_constraints_allows_message() -> None:
    in_scope, details = is_message_in_scope("How to make pizza?", None)
    assert in_scope is True
    assert details is None


def test_phrase_match_detected() -> None:
    pc = PersonaConstraints(out_of_scope=["medical advice", "recipes"])
    in_scope, details = is_message_in_scope("How do I get medical advice?", pc)
    assert in_scope is False
    assert details is not None
    assert details.get("token") in ("medical advice", "recipes")


def test_case_insensitive_match() -> None:
    pc = PersonaConstraints(out_of_scope=["Medical Advice"])
    in_scope, _ = is_message_in_scope("i need MEDICAL advice", pc)
    assert in_scope is False


def test_regex_slash_delimited() -> None:
    pc = PersonaConstraints(out_of_scope=["/pizza|pizza recipe/"])
    in_scope, details = is_message_in_scope("How to make pizza", pc)
    assert in_scope is False
    assert details is not None
    assert details.get("reason") == "regex"


def test_regex_prefix_re() -> None:
    pc = PersonaConstraints(out_of_scope=["re:\\bpizza\\b"])
    in_scope, _ = is_message_in_scope("I like pizza a lot", pc)
    assert in_scope is False
