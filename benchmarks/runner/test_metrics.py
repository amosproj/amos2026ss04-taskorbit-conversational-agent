"""Tests for benchmark metrics helpers."""

from __future__ import annotations

import sys
from pathlib import Path

_RUNNER_DIR = Path(__file__).parent
if str(_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNNER_DIR))

from metrics import (  # noqa: E402
    component_latencies_from_api_response,
    pipeline_total_ms_from_api_response,
)


def test_component_latencies_from_api_response_maps_stages() -> None:
    data = {
        "latency_ms": {
            "llm_call": 812.4,
            "tool_call": 15.2,
            "total": 905.7,
        }
    }
    result = component_latencies_from_api_response(data)
    assert result == {"llm": 812.4, "tool_call": 15.2}


def test_component_latencies_from_api_response_empty_when_missing() -> None:
    assert component_latencies_from_api_response({}) == {}


def test_pipeline_total_ms_prefers_api_total() -> None:
    data = {"latency_ms": {"total": 400.0}}
    assert pipeline_total_ms_from_api_response(data, fallback_ms=999.0) == 400.0


def test_pipeline_total_ms_falls_back_to_wall_clock() -> None:
    assert pipeline_total_ms_from_api_response({}, fallback_ms=250.5) == 250.5
