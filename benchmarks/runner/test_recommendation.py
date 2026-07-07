"""Tests for default configuration recommendation — issue #68."""

from __future__ import annotations

import sys
from pathlib import Path

_RUNNER_DIR = Path(__file__).parent
if str(_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNNER_DIR))

from recommendation import format_recommendation_section, recommend_default_config  # noqa: E402


def _row(config_label: str, total: float, expects_tool: bool, invoked: bool) -> dict:
    return {
        "config_label": config_label,
        "path": "text",
        "prompt": {
            "category": "short_no_tool",
            "expects_tool": expects_tool,
            "expected_tool_type": None,
        },
        "latency_ms": {"total": total},
        "tool_reliability": {
            "tool_was_invoked": invoked,
            "invoked_tool_type": None,
        },
    }


def test_recommend_lowest_latency_config() -> None:
    rows = [
        _row("cfg-fast", 100.0, False, False),
        _row("cfg-slow", 300.0, False, False),
    ]
    result = recommend_default_config(rows)
    assert result["recommended_config"] == "cfg-fast"
    assert "lowest avg total latency" in result["reason"]


def test_recommend_tie_break_on_reliability() -> None:
    rows = [
        _row("cfg-a", 100.0, False, False),
        _row("cfg-b", 105.0, False, True),  # unexpected tool → fail reliability
        _row("cfg-b", 105.0, False, False),
    ]
    result = recommend_default_config(rows)
    assert result["recommended_config"] == "cfg-a"


def test_format_recommendation_section_lists_candidates() -> None:
    rows = [
        _row("cfg-alpha", 120.0, False, False),
        _row("cfg-beta", 200.0, False, False),
    ]
    text = format_recommendation_section(rows)
    assert "cfg-alpha" in text
    assert "Recommended: cfg-alpha" in text
