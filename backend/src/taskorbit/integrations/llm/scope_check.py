"""Lightweight pre-LLM scope classifier.

Provides a deterministic, fast check that can short-circuit the LLM when a
user message clearly falls into an agent's configured out_of_scope list.

Matching rules (practical default):
- If an out_of_scope entry is None/empty, it's ignored.
- If an entry starts with "re:", the remainder is treated as a raw regex.
- If an entry is enclosed in forward slashes "/.../", the interior is treated as regex.
- Otherwise the entry is matched as a case-insensitive whole-word/phrase via regex
  (word boundaries are applied so "medical" doesn't match "academics").

Returns: (in_scope: bool, details: dict|None)
"""
from __future__ import annotations

import re
from typing import Any

from taskorbit.types import PersonaConstraints


def _try_regex_search(pattern: str, text: str) -> re.Match | None:
    try:
        return re.search(pattern, text, flags=re.IGNORECASE)
    except re.error:
        # Invalid regex — caller will fall back to substring matching if appropriate
        return None


def is_message_in_scope(message: str, persona_constraints: PersonaConstraints | None) -> tuple[bool, dict | None]:
    """Return (in_scope, details).

    in_scope==True means the message is allowed and the LLM may be invoked.
    in_scope==False means the message matched an out-of-scope rule and should be
    refused by the orchestrator without contacting the LLM.
    """
    if not persona_constraints:
        return True, None

    if not persona_constraints.out_of_scope:
        return True, None

    text = message or ""

    for token in persona_constraints.out_of_scope:
        if not token:
            continue
        t = token.strip()
        if not t:
            continue

        # Raw regex with explicit prefix: re:<pattern>
        if t.lower().startswith("re:"):
            pattern = t[3:].strip()
            if not pattern:
                continue
            m = _try_regex_search(pattern, text)
            if m:
                return False, {"reason": "regex", "token": token, "match": m.group(0)}
            continue

        # Slash-delimited regex: /pattern/
        if t.startswith("/") and t.endswith("/") and len(t) >= 2:
            pattern = t[1:-1]
            if not pattern:
                continue
            m = _try_regex_search(pattern, text)
            if m:
                return False, {"reason": "regex", "token": token, "match": m.group(0)}
            continue

        # Phrase match: use word-boundary-safe search
        pattern = r"\b" + re.escape(t) + r"\b"
        m = _try_regex_search(pattern, text)
        if m:
            return False, {"reason": "phrase", "token": token, "match": m.group(0)}

    # Heuristic: detect recipe/cooking requests when the agent explicitly lists
    # cooking/recipes as out-of-scope. This catches queries like "How do you make
    # pizza?" even when the out_of_scope list contains only the abstract terms
    # ("recipes", "cooking").
    try:
        lowered_out = " ".join([str(t).lower() for t in persona_constraints.out_of_scope or []])
    except Exception:
        lowered_out = ""

    if any(k in lowered_out for k in ("recipe", "recipes", "cook", "cooking", "bake", "prepare")):
        recipe_pattern = r"\b(how (do )?(you )?make|how to|recipe|recipes|cook|cooking|bake|prepare|what(?:'s| is) the recipe|ingredients)\b"
        m = _try_regex_search(recipe_pattern, text)
        if m:
            return False, {"reason": "heuristic", "token": "cooking_recipe", "match": m.group(0)}

    return True, None
