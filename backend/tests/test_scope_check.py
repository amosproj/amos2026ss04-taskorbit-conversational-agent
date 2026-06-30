"""Unit tests for the lightweight pre-LLM scope classifier."""

from __future__ import annotations

from taskorbit.integrations.llm.scope_check import is_message_in_scope
from taskorbit.types import PersonaConstraints


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


def test_buy_pizza_heuristic_when_cooking_out_of_scope() -> None:
    pc = PersonaConstraints(out_of_scope=["recipes", "cooking"])
    in_scope, details = is_message_in_scope("I want to buy a pizza.", pc)
    assert in_scope is False
    assert details is not None
    assert details.get("reason") == "heuristic"


def test_cars_in_scope_for_dealership_agent() -> None:
    pc = PersonaConstraints(
        out_of_scope=["recipes", "cooking"],
        scope="Car sales at AutoDealership.",
    )
    in_scope, _ = is_message_in_scope("Can you tell me about cars?", pc)
    assert in_scope is True


def test_buy_car_in_scope_for_dealership_agent() -> None:
    pc = PersonaConstraints(out_of_scope=["recipes", "cooking"])
    in_scope, _ = is_message_in_scope("I want to buy a car", pc)
    assert in_scope is True
