"""Translate taskorbit Message objects to provider-specific wire formats.


Each concrete LLM client (OpenAIClient, GeminiClient) calls one of these
helpers in its `generate` implementation so that message-format mapping
logic stays out of the clients themselves.
"""

from __future__ import annotations

from taskorbit.types import Message, MessageRole


def to_openai_messages(messages: list[Message]) -> list[dict[str, str]]:
    """Translate to OpenAI chat-completion format.

    OpenAI's `chat.completions.create` accepts messages as a list of
    `{"role": str, "content": str}` dicts where role is one of "user",
    "assistant", or "system". Our MessageRole enum values are already
    lowercase strings that match — this is essentially a shape mapping.
    """
    return [{"role": m.role.value, "content": m.content} for m in messages]


def to_gemini_contents(messages: list[Message]) -> list[dict[str, list[dict[str, str]]]]:
    """Translate to google-genai contents format.

    google-genai uses ``[{"role": "user" | "model", "parts": [{"text": ...}]}]``.
    System messages are NOT placed in `contents` — they go into the
    `system_instruction` parameter of `GenerateContentConfig`. Callers
    should pass the system prompt separately; this helper filters out
    system messages so they aren't duplicated.

    Assistant turns are mapped to role "model" per the genai convention.
    """
    role_map = {
        MessageRole.USER: "user",
        MessageRole.ASSISTANT: "model",
    }
    return [
        {"role": role_map[m.role], "parts": [{"text": m.content}]}
        for m in messages
        if m.role in role_map
    ]
