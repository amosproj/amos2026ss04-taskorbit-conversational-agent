"""Tests for per-turn benchmark expectations (#68)."""

from __future__ import annotations

import sys
from pathlib import Path

_RUNNER_DIR = Path(__file__).parent
if str(_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNNER_DIR))

from turn_expectations import (  # noqa: E402
    response_status_ok,
    turn_expected_status,
    turn_tool_expectations,
)

_APPT = {
    "expects_tool": True,
    "expected_tool_type": "data_extraction",
    "tool_on_final_turn_only": True,
    "expected_status": "success",
}

_END_CALL = {
    "expects_tool": True,
    "expected_tool_type": "end_call",
    "expected_status": "ended",
}


def test_tool_expected_only_on_final_turn() -> None:
    assert turn_tool_expectations(_APPT, 0, 5) == (False, None)
    assert turn_tool_expectations(_APPT, 3, 5) == (False, None)
    assert turn_tool_expectations(_APPT, 4, 5) == (True, "data_extraction")


def test_expected_status_only_on_final_turn() -> None:
    assert turn_expected_status(_END_CALL, 0, 1) == "ended"
    assert turn_expected_status(_APPT, 0, 5) == "success"
    assert turn_expected_status(_APPT, 4, 5) == "success"


def test_response_status_ok_uses_prompt_expected_status() -> None:
    assert response_status_ok({"status": "ended", "prompt": {"expected_status": "ended"}})
    assert not response_status_ok({"status": "success", "prompt": {"expected_status": "ended"}})
