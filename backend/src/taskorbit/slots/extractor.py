"""LLM-driven slot extractor for structured task inputs."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from taskorbit.slots.models import SlotExtractionResult, SlotValue
from taskorbit.types import LLMConfig, Message, MessageRole


def _normalize_email_value(value: str) -> str:
    """Normalize a potentially malformed email string before validation.

    Speech transcription (STT) often produces email addresses in spoken form
    or with trailing punctuation that breaks format validation. This function
    converts those artifacts to a canonical address so the correct value is
    stored in SlotValue and echoed in confirmation messages.

    Handles:
    - Spoken "at the rate" / standalone " at " → "@"
    - " dot " → "."
    - Stray spaces around "@" and "." (e.g. "alice @ gmail . com")
    - Trailing punctuation (period, comma, semicolon)
    """
    v = value.strip()

    # Spoken "at the rate" (common STT output for @)
    v = re.sub(r"\bat\s+the\s+rate\b", "@", v, flags=re.IGNORECASE)

    # Standalone " at " between non-space characters → "@"
    # Requires a word character on each side to avoid replacing "at" in words.
    v = re.sub(r"(?<=\S)\s+at\s+(?=\S)", "@", v, flags=re.IGNORECASE)

    # Spoken " dot " → "."
    v = re.sub(r"\s+dot\s+", ".", v, flags=re.IGNORECASE)

    # Collapse spaces around "@" and "."
    v = re.sub(r"\s*@\s*", "@", v)
    v = re.sub(r"\s*\.\s*", ".", v)

    # Strip trailing punctuation left over from sentence endings
    v = v.rstrip(".,;")

    return v


# Minimum format checks per slot type — rejects clearly malformed values so the
# agent asks the user to repeat them rather than silently storing garbage.
# TLD segment requires alphabetic characters only (2+ chars) so trailing
# punctuation that survived normalization is caught rather than silently stored.
_SLOT_VALIDATORS: dict[str, Callable[[Any], bool]] = {
    "email": lambda v: isinstance(v, str) and bool(re.match(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$", v)),
    "phone": lambda v: isinstance(v, str) and len(re.sub(r"[^\d]", "", v)) >= 7,
    "date": lambda v: isinstance(v, str) and bool(re.match(r"^\d{4}-\d{2}-\d{2}$", v)),
}


class SlotExtractor:
    """Extracts structured slot values from a conversation using an LLM call.

    The extractor is intentionally stateless — each ``extract`` call is
    independent so it can be reused across turns without side effects.
    """

    def __init__(
        self,
        llm_fn: Callable[[str, list[Message], LLMConfig], Awaitable[str]],
        llm_config: LLMConfig,
    ) -> None:
        self._llm_fn = llm_fn
        self._llm_config = llm_config

    async def extract(
        self,
        messages: list[Message],
        required_inputs: list[dict[str, Any]],
        guidance: str = "",
    ) -> SlotExtractionResult:
        """Run a single extraction pass over *messages* for *required_inputs*.

        Returns a :class:`SlotExtractionResult` describing which slots were
        filled and which are still missing.  On any JSON parse failure the
        result marks all required slots as missing so the caller can ask the
        user to repeat the information.

        *guidance* is optional per-tool text (e.g. an external_api tool's
        description) telling the extractor how to convert what the user said
        into the exact value a field needs, such as mapping a country to a
        timezone identifier. It is empty for data-extraction tools, whose
        extraction stays strictly literal.
        """
        system_prompt = self._build_extraction_prompt(required_inputs, guidance)
        # Append a trigger message so the last thing the LLM sees is an
        # explicit instruction to output JSON — prevents it from responding
        # conversationally when the last user turn is a question rather than
        # a data-providing statement.
        extraction_messages = messages + [
            Message(
                role=MessageRole.USER,
                content="Based ONLY on the conversation above, extract all provided data and return the JSON object now.",
            )
        ]
        raw = await self._llm_fn(system_prompt, extraction_messages, self._llm_config)
        return self._parse_response(raw, required_inputs)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_extraction_prompt(
        self, required_inputs: list[dict[str, Any]], guidance: str = ""
    ) -> str:
        field_lines = "\n".join(
            f'  - {f["name"]} ({f["type"]}, required={f.get("required", True)})'
            for f in required_inputs
        )
        field_names = ", ".join(f'"{f["name"]}"' for f in required_inputs)
        has_email = any(f["type"] == "email" for f in required_inputs)
        email_hint = (
            "\n- For email fields: convert spoken forms to standard format "
            '(e.g. "alice at the rate gmail dot com" → "alice@gmail.com"). '
            "Strip any trailing punctuation."
            if has_email
            else ""
        )
        # Optional per-tool guidance lets the extractor convert what the user
        # said into the exact value a field needs (e.g. a country -> a timezone
        # identifier). Framed as an explicit exception so the strict "do not
        # infer" rule below is unchanged for data-extraction tools, which pass
        # no guidance. Converting information the user actually gave is not the
        # same as inventing a value, so a field whose underlying detail the
        # user never provided still stays null.
        guidance_hint = (
            "\n- Conversion guidance for these fields: apply the guidance below to "
            "convert what the user actually said into each field's value. Convert "
            "only; do NOT choose among multiple valid conversions, and if the user "
            "has not stated the underlying detail or the correct conversion is "
            f"ambiguous, keep the field null. Guidance: {guidance.strip()}"
            if guidance and guidance.strip()
            else ""
        )
        return (
            "You are a JSON data extraction function. "
            "Your ONLY output must be a valid JSON object — no prose, no markdown, no conversation.\n\n"
            "Read the ENTIRE conversation history and extract every field the user has explicitly provided:\n"
            f"{field_lines}\n\n"
            f"Output format: {{{field_names}}}\n\n"
            "Rules:\n"
            "- Use null for any field not yet provided by the user.\n"
            "- Do NOT infer, guess, or assume values.\n"
            "- Do NOT respond to questions or continue the conversation.\n"
            f"- Output ONLY the JSON object, nothing else.{email_hint}{guidance_hint}"
        )

    def _parse_response(
        self,
        raw: str,
        required_inputs: list[dict[str, Any]],
    ) -> SlotExtractionResult:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # Strip ```json ... ``` or plain ``` ... ``` fences
            lines = cleaned.splitlines()
            inner = [line for line in lines if not line.startswith("```")]
            cleaned = "\n".join(inner).strip()

        required_names = {f["name"] for f in required_inputs if f.get("required", True)}
        type_map = {f["name"]: f["type"] for f in required_inputs}

        try:
            data: dict[str, Any] = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return SlotExtractionResult(missing=sorted(required_names))

        filled: dict[str, SlotValue] = {}
        for f in required_inputs:
            name = f["name"]
            value = data.get(name)
            if value is None:
                continue
            slot_type = type_map[name]
            if slot_type == "email" and isinstance(value, str):
                value = _normalize_email_value(value)
            validator = _SLOT_VALIDATORS.get(slot_type)
            if validator is not None and not validator(value):
                continue
            filled[name] = SlotValue(name=name, value=value, slot_type=slot_type)

        missing = sorted(name for name in required_names if name not in filled)
        return SlotExtractionResult(filled=filled, missing=missing)
