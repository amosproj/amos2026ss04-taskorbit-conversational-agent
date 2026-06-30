"""Unit tests for the authoritative reliability evaluation layer — issue #68."""

from __future__ import annotations

import sys
from pathlib import Path

_RUNNER_DIR = Path(__file__).parent
if str(_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNNER_DIR))

from reliability import evaluate_reliability_authoritative, summarize_reliability  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(
    expects_tool: bool,
    expected_tool_type: str | None,
    tool_was_invoked: bool,
    invoked_tool_type: str | None,
    result_incorporated_in_reply: bool | None = None,
    config_label: str = "cfg-a",
    category: str = "short_no_tool",
) -> dict:
    return {
        "config_label": config_label,
        "prompt": {
            "expects_tool": expects_tool,
            "expected_tool_type": expected_tool_type,
            "category": category,
        },
        "tool_reliability": {
            "tool_was_invoked": tool_was_invoked,
            "invoked_tool_type": invoked_tool_type,
            "correct_tool_selected": None,
            "result_incorporated_in_reply": result_incorporated_in_reply,
        },
    }


# ---------------------------------------------------------------------------
# No-tool cases
# ---------------------------------------------------------------------------


def test_no_tool_pass_when_no_tool_fired() -> None:
    verdict = evaluate_reliability_authoritative(
        _row(expects_tool=False, expected_tool_type=None, tool_was_invoked=False, invoked_tool_type=None)
    )
    assert verdict["reliability_pass"] is True
    assert verdict["tool_correct"] is True
    assert verdict["result_incorporated"] is None
    assert verdict["reason"] == "no tool fired as expected"


def test_no_tool_fail_when_tool_fired_unexpectedly() -> None:
    verdict = evaluate_reliability_authoritative(
        _row(
            expects_tool=False,
            expected_tool_type=None,
            tool_was_invoked=True,
            invoked_tool_type="agent_transfer",
        )
    )
    assert verdict["reliability_pass"] is False
    assert verdict["tool_correct"] is False
    assert verdict["result_incorporated"] is None
    assert verdict["reason"] == "tool fired unexpectedly: agent_transfer"


# ---------------------------------------------------------------------------
# With-tool cases — correct invocation
# ---------------------------------------------------------------------------


def test_with_tool_pass_correct_type() -> None:
    verdict = evaluate_reliability_authoritative(
        _row(
            expects_tool=True,
            expected_tool_type="agent_transfer",
            tool_was_invoked=True,
            invoked_tool_type="agent_transfer",
            category="short_with_tool",
        )
    )
    assert verdict["reliability_pass"] is True
    assert verdict["tool_correct"] is True
    assert verdict["reason"] == "correct tool invoked: agent_transfer"


def test_with_tool_fail_wrong_type() -> None:
    verdict = evaluate_reliability_authoritative(
        _row(
            expects_tool=True,
            expected_tool_type="end_call",
            tool_was_invoked=True,
            invoked_tool_type="agent_transfer",
            category="short_with_tool",
        )
    )
    assert verdict["reliability_pass"] is False
    assert verdict["tool_correct"] is False
    assert verdict["reason"] == "expected end_call, got agent_transfer"


def test_with_tool_fail_no_invocation() -> None:
    verdict = evaluate_reliability_authoritative(
        _row(
            expects_tool=True,
            expected_tool_type="data_extraction",
            tool_was_invoked=False,
            invoked_tool_type=None,
            category="long_with_tool",
        )
    )
    assert verdict["reliability_pass"] is False
    assert verdict["tool_correct"] is False
    assert verdict["reason"] == "expected data_extraction, no tool invoked"


# ---------------------------------------------------------------------------
# data_extraction — result_incorporated passthrough from harness
# ---------------------------------------------------------------------------


def test_data_extraction_result_incorporated_true() -> None:
    verdict = evaluate_reliability_authoritative(
        _row(
            expects_tool=True,
            expected_tool_type="data_extraction",
            tool_was_invoked=True,
            invoked_tool_type="data_extraction",
            result_incorporated_in_reply=True,
            category="long_with_tool",
        )
    )
    assert verdict["reliability_pass"] is True
    assert verdict["tool_correct"] is True
    assert verdict["result_incorporated"] is True


def test_data_extraction_result_incorporated_false() -> None:
    verdict = evaluate_reliability_authoritative(
        _row(
            expects_tool=True,
            expected_tool_type="data_extraction",
            tool_was_invoked=True,
            invoked_tool_type="data_extraction",
            result_incorporated_in_reply=False,
            category="long_with_tool",
        )
    )
    assert verdict["reliability_pass"] is False
    assert verdict["tool_correct"] is True
    assert verdict["result_incorporated"] is False
    assert "not reflected in reply" in verdict["reason"]


# ---------------------------------------------------------------------------
# Immediate tools — result_incorporated is N/A
# ---------------------------------------------------------------------------


def test_agent_transfer_result_incorporated_is_not_applicable() -> None:
    verdict = evaluate_reliability_authoritative(
        _row(
            expects_tool=True,
            expected_tool_type="agent_transfer",
            tool_was_invoked=True,
            invoked_tool_type="agent_transfer",
            category="short_with_tool",
        )
    )
    assert verdict["reliability_pass"] is True
    assert verdict["result_incorporated"] is None


def test_end_call_result_incorporated_is_not_applicable() -> None:
    verdict = evaluate_reliability_authoritative(
        _row(
            expects_tool=True,
            expected_tool_type="end_call",
            tool_was_invoked=True,
            invoked_tool_type="end_call",
            category="short_with_tool",
        )
    )
    assert verdict["reliability_pass"] is True
    assert verdict["result_incorporated"] is None


# ---------------------------------------------------------------------------
# summarize_reliability aggregation
# ---------------------------------------------------------------------------


def test_summarize_reliability_counts_per_bucket() -> None:
    rows = [
        _row(False, None, False, None, config_label="cfg-a", category="short_no_tool"),  # pass
        _row(False, None, True, "agent_transfer", config_label="cfg-a", category="short_no_tool"),  # fail
        _row(True, "end_call", True, "end_call", config_label="cfg-a", category="short_with_tool"),  # pass
        _row(True, "end_call", True, "end_call", config_label="cfg-a", category="short_with_tool"),  # pass
        _row(True, "end_call", False, None, config_label="cfg-b", category="short_with_tool"),  # fail
    ]
    result = summarize_reliability(rows)

    a_no_tool = result["cfg-a__short_no_tool"]
    assert a_no_tool["pass"] == 1
    assert a_no_tool["fail"] == 1
    assert a_no_tool["total"] == 2
    assert a_no_tool["reliability_rate"] == 0.5

    a_with_tool = result["cfg-a__short_with_tool"]
    assert a_with_tool["pass"] == 2
    assert a_with_tool["fail"] == 0
    assert a_with_tool["reliability_rate"] == 1.0

    b_with_tool = result["cfg-b__short_with_tool"]
    assert b_with_tool["pass"] == 0
    assert b_with_tool["fail"] == 1
    assert b_with_tool["reliability_rate"] == 0.0


def test_summarize_reliability_empty_input() -> None:
    assert summarize_reliability([]) == {}
