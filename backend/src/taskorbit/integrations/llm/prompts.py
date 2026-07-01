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
    """Return ``system_prompt`` wrapped with persona guardrails (#69, #168).

    Leads with a concise top-priority "stay in role" directive (primacy) and
    appends the detailed authorized-scope, forbidden-topics, and refusal-template
    block (recency). The top directive is the primary prompt guard in
    environments where the code-level scope check is disabled (e.g. staging /
    production), so it is placed where the model weights it most.

    No-op (returns ``system_prompt`` unchanged) when ``constraints`` is None or
    when every field on the constraints object is empty. This keeps the behaviour
    fully backward-compatible for agent configs that do not opt into guardrails.
    """
    if constraints is None:
        return system_prompt
    lines: list[str] = []

    # Imperative, high-authority headers like "CORE CONSTRAINT" are used
    # to ensure the LLM prioritizes these guardrails over general conversational drift.

    if constraints.scope:
        lines.append(f"CORE CONSTRAINT - Authorized Scope: {constraints.scope}")

    if constraints.out_of_scope:
        joined = ", ".join(constraints.out_of_scope)
        lines.append(
            f"CORE CONSTRAINT - Forbidden Topics (you MUST politely refuse and redirect): {joined}"
        )

    if constraints.refusal_template:
        lines.append(
            f'REQUIRED REFUSAL PHRASE (use this for redirection): "{constraints.refusal_template}"'
        )

    if not lines:
        return system_prompt

    # Top-anchored guardrail (#168): models weight the earliest instructions most,
    # and where the code-level scope check is off this is the primary guard.
    header = (
        "TOP PRIORITY - STAY IN ROLE: You are strictly limited to your authorized "
        "scope (defined below). If the user's request falls outside that scope or "
        "touches a forbidden topic, do NOT answer it; politely decline and redirect "
        "using your required refusal phrase."
    )
    return header + "\n\n" + system_prompt + "\n\n" + "\n".join(lines)
