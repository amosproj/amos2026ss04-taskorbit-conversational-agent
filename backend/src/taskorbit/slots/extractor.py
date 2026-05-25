"""LLM-driven slot extractor for structured task inputs."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from taskorbit.slots.models import SlotExtractionResult, SlotValue
from taskorbit.types import LLMConfig, Message


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
    ) -> SlotExtractionResult:
        """Run a single extraction pass over *messages* for *required_inputs*.

        Returns a :class:`SlotExtractionResult` describing which slots were
        filled and which are still missing.  On any JSON parse failure the
        result marks all required slots as missing so the caller can ask the
        user to repeat the information.
        """
        system_prompt = self._build_extraction_prompt(required_inputs)
        raw = await self._llm_fn(system_prompt, messages, self._llm_config)
        return self._parse_response(raw, required_inputs)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_extraction_prompt(self, required_inputs: list[dict[str, Any]]) -> str:
        field_lines = "\n".join(
            f'  - {f["name"]} ({f["type"]}, required={f.get("required", True)})'
            for f in required_inputs
        )
        field_names = ", ".join(f'"{f["name"]}"' for f in required_inputs)
        return (
            "You are a structured data extractor. "
            "Read the conversation and extract the following fields:\n"
            f"{field_lines}\n\n"
            "Return ONLY valid JSON with exactly these keys: "
            f"{{{field_names}}}. "
            "Use null for any field not yet mentioned by the user. "
            "Do not add any explanation or markdown."
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
            if value is not None:
                filled[name] = SlotValue(name=name, value=value, slot_type=type_map[name])

        missing = sorted(name for name in required_names if name not in filled)
        return SlotExtractionResult(filled=filled, missing=missing)
