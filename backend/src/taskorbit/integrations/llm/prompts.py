"""Utilities for constructing system prompts that enable multilingual behaviour.

Appends language-instruction addenda to a given system prompt rather than
issuing a separate LLM call for language detection.
"""


def with_same_language_instruction(system_prompt: str) -> str:
    """Return system_prompt with the same-language directive appended."""
    return system_prompt + "\n\nRespond in the same language as the user's most recent message."
