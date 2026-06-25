"""Tests for component benchmark runner and schema (#68)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

_BENCH_ROOT = Path(__file__).parent.parent
_RUNNER_DIR = Path(__file__).parent
if str(_BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BENCH_ROOT))
if str(_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNNER_DIR))

from benchmark_schema import evaluate_tool_reliability
from component_config import ComponentBenchmarkConfig
from component_runner import ComponentBenchmarkRunner


def test_component_config_loads_yaml() -> None:
    config_path = _BENCH_ROOT / "configs" / "component-benchmark.yaml"
    config = ComponentBenchmarkConfig.from_yaml(config_path)
    assert config.name == "component-benchmark"
    assert len(config.configs) >= 2
    is_valid, msg = config.validate()
    assert is_valid, msg


def test_component_runner_dry_run_writes_schema_rows() -> None:
    config_path = _BENCH_ROOT / "configs" / "component-benchmark.yaml"
    config = ComponentBenchmarkConfig.from_yaml(config_path)

    with tempfile.TemporaryDirectory() as tmp:
        runner = ComponentBenchmarkRunner(results_dir=tmp, dry_run=True)
        results_file, summary = asyncio.run(runner.run_experiment(config))

        assert results_file.exists()
        assert summary["total_rows"] > 0

        lines = results_file.read_text().strip().splitlines()
        row = json.loads(lines[0])
        assert "config" in row
        assert "prompt" in row
        assert "latency_ms" in row
        assert "tool_reliability" in row
        assert row["path"] == "text"
        assert row["config"]["llm_model"]
        assert row["config_label"]


def test_evaluate_tool_reliability_no_tool_case() -> None:
    reliability = evaluate_tool_reliability(
        {"tool_invoked": None},
        expects_tool=False,
        expected_tool_type=None,
    )
    assert reliability.tool_was_invoked is False
    assert reliability.correct_tool_selected is True


def test_evaluate_tool_reliability_data_extraction_match() -> None:
    response = {
        "tool_invoked": {"type": "data_extraction"},
        "extracted_slots": {"caller_name": "Alice Brown"},
        "reply": {"content": "Thanks Alice Brown, your appointment is noted."},
    }
    reliability = evaluate_tool_reliability(
        response,
        expects_tool=True,
        expected_tool_type="data_extraction",
    )
    assert reliability.correct_tool_selected is True
    assert reliability.result_incorporated_in_reply is True
