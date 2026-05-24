from taskorbit.integrations.llm.prompts import (
    with_persona_guardrails,
    with_same_language_instruction,
)
from taskorbit.types import PersonaConstraints

# ---------------------------------------------------------------------------
# with_same_language_instruction
# ---------------------------------------------------------------------------


def test_appends_instruction():
    result = with_same_language_instruction("You are a helpful assistant.")
    assert "You are a helpful assistant." in result
    assert "Respond in the same language" in result


def test_preserves_original_prompt():
    prompt = "You are a helpful assistant."
    result = with_same_language_instruction(prompt)
    assert result.startswith(prompt)


def test_separates_with_blank_line():
    prompt = "You are a helpful assistant."
    result = with_same_language_instruction(prompt)
    assert "\n\n" in result


# ---------------------------------------------------------------------------
# with_persona_guardrails
# ---------------------------------------------------------------------------


BASE_PROMPT = "You are John.\nPersona: TechStore customer support."


def test_guardrails_none_returns_unchanged():
    """No constraints object → prompt is returned byte-for-byte."""
    assert with_persona_guardrails(BASE_PROMPT, None) == BASE_PROMPT


def test_guardrails_empty_constraints_returns_unchanged():
    """Constraints object with every field empty is a no-op."""
    empty = PersonaConstraints()
    assert with_persona_guardrails(BASE_PROMPT, empty) == BASE_PROMPT


def test_guardrails_scope_only_appended():
    """Only ``scope`` set → only the Scope line is appended."""
    constraints = PersonaConstraints(scope="TechStore customer service.")
    result = with_persona_guardrails(BASE_PROMPT, constraints)
    assert result.startswith(BASE_PROMPT)
    assert "Scope: TechStore customer service." in result
    assert "Out of scope" not in result
    assert "When asked something out of scope" not in result


def test_guardrails_out_of_scope_joined_with_commas():
    """``out_of_scope`` list is rendered as a comma-joined string."""
    constraints = PersonaConstraints(out_of_scope=["therapy", "medical advice", "legal advice"])
    result = with_persona_guardrails(BASE_PROMPT, constraints)
    assert "Out of scope (politely redirect): therapy, medical advice, legal advice" in result


def test_guardrails_refusal_template_quoted():
    """``refusal_template`` is rendered inside double quotes."""
    constraints = PersonaConstraints(refusal_template="I can only help with TechStore.")
    result = with_persona_guardrails(BASE_PROMPT, constraints)
    assert '"I can only help with TechStore."' in result


def test_guardrails_all_three_fields_appear_in_order():
    """All three lines appear in the documented order: scope → out_of_scope → refusal."""
    constraints = PersonaConstraints(
        scope="TechStore customer service.",
        out_of_scope=["therapy", "legal advice"],
        refusal_template="I can only help with TechStore.",
    )
    result = with_persona_guardrails(BASE_PROMPT, constraints)
    scope_idx = result.index("Scope:")
    out_of_scope_idx = result.index("Out of scope")
    refusal_idx = result.index("When asked something out of scope")
    assert scope_idx < out_of_scope_idx < refusal_idx


def test_guardrails_preserves_original_prompt():
    """Original prompt body is never mutated, only appended to."""
    constraints = PersonaConstraints(scope="A scope.")
    result = with_persona_guardrails(BASE_PROMPT, constraints)
    assert result.startswith(BASE_PROMPT)
    assert "\n\n" in result
