"""Per-turn expectations for multi-step component benchmark prompts (#68)."""

from __future__ import annotations

from typing import Any


def turn_tool_expectations(
    prompt_def: dict[str, Any],
    turn_index: int,
    turn_count: int,
) -> tuple[bool, str | None]:
    """Return (expects_tool, expected_tool_type) for a single turn."""
    expects_tool = bool(prompt_def.get("expects_tool"))
    expected_type: str | None = prompt_def.get("expected_tool_type")

    if expects_tool and prompt_def.get("tool_on_final_turn_only"):
        is_final = turn_index >= turn_count - 1
        if not is_final:
            return False, None

    if not expects_tool:
        return False, None
    return True, expected_type


def turn_expected_status(
    prompt_def: dict[str, Any],
    turn_index: int,
    turn_count: int,
) -> str:
    """Expected ConversationResponse.status for this turn."""
    if turn_index < turn_count - 1:
        return "success"
    return str(prompt_def.get("expected_status") or "success")


def response_status_ok(row: dict[str, Any]) -> bool:
    """True when the row's status matches the per-turn expected_status on the prompt."""
    actual = row.get("status")
    expected = (row.get("prompt") or {}).get("expected_status") or "success"
    return actual == expected
