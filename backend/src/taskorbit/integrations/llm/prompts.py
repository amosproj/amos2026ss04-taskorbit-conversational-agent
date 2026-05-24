"""Utilities for constructing system prompts that enable multilingual behaviour.

Appends language-instruction addenda to a given system prompt rather than
issuing a separate LLM call for language detection.
"""

from __future__ import annotations

from taskorbit.types import PersonaConstraints


def with_same_language_instruction(system_prompt: str) -> str:
    """Return system_prompt with the same-language directive appended."""
    return system_prompt + "\n\nRespond in the same language as the user's most recent message."


def with_persona_guardrails(
    system_prompt: str,
    constraints: PersonaConstraints | None,
) -> str:
    """Return ``system_prompt`` with persona scope, out-of-scope domains, and
    refusal template appended.

    No-op (returns ``system_prompt`` unchanged) when ``constraints`` is None
    or when every field on the constraints object is empty. This keeps the
    behaviour fully backward-compatible for agent configs that do not opt
    into the guardrails (ticket #69).
    """
    if constraints is None:
        return system_prompt
    lines: list[str] = []
    if constraints.scope:
        lines.append(f"Scope: {constraints.scope}")
    if constraints.out_of_scope:
        joined = ", ".join(constraints.out_of_scope)
        lines.append(f"Out of scope (politely redirect): {joined}")
    if constraints.refusal_template:
        lines.append(
            f'When asked something out of scope, respond: "{constraints.refusal_template}"'
        )
    if not lines:
        return system_prompt
    return system_prompt + "\n\n" + "\n".join(lines)
