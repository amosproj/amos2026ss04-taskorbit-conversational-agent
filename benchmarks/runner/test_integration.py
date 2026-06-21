"""Integration tests for the TaskOrbit benchmarking environment.

Tests validate that the full pipeline — config loading → dry-run execution →
result serialization → schema validation — works end-to-end without requiring
a live backend or real API keys.

Run from the project root:
    pytest benchmarks/runner/test_integration.py -v
"""

from __future__ import annotations

import asyncio
import csv
import json
import sys
import tempfile
from pathlib import Path

import pytest

# Resolve paths relative to this file so tests run from any working directory.
_BENCH_ROOT = Path(__file__).parent.parent
_RUNNER_DIR = Path(__file__).parent

# Add benchmarks/ (parent of runner package) so `runner.X` imports work.
# Also add runner/ itself so the modules' own bare imports (e.g. `from config import`)
# resolve correctly when runner.py, config.py etc. are executed.
if str(_BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BENCH_ROOT))
if str(_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNNER_DIR))

from runner.config import ExperimentConfig  # noqa: E402
from runner.metrics import ComponentTimer, capture_component_latencies, capture_system_metrics, export_to_otel  # noqa: E402
from runner.runner import BenchmarkRunner  # noqa: E402
from runner.storage import ResultWriter, TrialMetrics  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASELINE_LOCAL = _BENCH_ROOT / "configs" / "baseline-local.yaml"
BASELINE_CLOUD = _BENCH_ROOT / "configs" / "baseline-cloud.yaml"


def _load_config(path: Path) -> ExperimentConfig:
    return ExperimentConfig.from_yaml(path)


def _run(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine synchronously (Python 3.11 compatible)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Test 1 — Dry-run baseline-local config produces valid results
# ---------------------------------------------------------------------------


class TestDryRunBaselineLocal:
    """Dry-run the open-source (OpenRouter / Qwen) config end-to-end."""

    def test_dry_run_baseline_local_exits_ok(self) -> None:
        """Dry-run must complete without raising and return a run_id."""
        config = _load_config(BASELINE_LOCAL)
        assert config.provider == "openrouter"
        assert "qwen" in config.model or "gemma" in config.model or config.model

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(results_dir=tmpdir, dry_run=True)
            run_id, results_file, summary = _run(runner.run_experiment(config))

            assert run_id, "run_id must not be empty"
            assert results_file.exists(), f"results file not found: {results_file}"
            assert summary["success_rate"] == 1.0

    def test_dry_run_baseline_local_results_jsonl_valid(self) -> None:
        """Every line in results.jsonl must be valid JSON with required fields."""
        config = _load_config(BASELINE_LOCAL)

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(results_dir=tmpdir, dry_run=True)
            _, results_file, _ = _run(runner.run_experiment(config))

            required = {"run_id", "timestamp", "trial_index", "metrics", "environment"}
            with open(results_file) as f:
                lines = [l for l in f if l.strip()]

            assert lines, "results.jsonl must not be empty"
            for line in lines:
                obj = json.loads(line)
                missing = required - obj.keys()
                assert not missing, f"Missing fields in JSONL line: {missing}"
                assert isinstance(obj["metrics"]["latency_ms"], float)
                assert isinstance(obj["metrics"]["success"], bool)


# ---------------------------------------------------------------------------
# Test 2 — Dry-run baseline-cloud config produces valid results
# ---------------------------------------------------------------------------


class TestDryRunBaselineCloud:
    """Dry-run the cloud (OpenAI) config end-to-end."""

    def test_dry_run_baseline_cloud_exits_ok(self) -> None:
        """Dry-run must complete without raising and return a run_id."""
        config = _load_config(BASELINE_CLOUD)
        assert config.provider == "openai"

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(results_dir=tmpdir, dry_run=True)
            run_id, results_file, summary = _run(runner.run_experiment(config))

            assert run_id
            assert results_file.exists()
            assert summary["total_trials"] >= 1

    def test_two_configs_produce_separate_runs(self) -> None:
        """Running both configs into the same results dir must produce 2 index rows."""
        local_cfg = _load_config(BASELINE_LOCAL)
        cloud_cfg = _load_config(BASELINE_CLOUD)

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(results_dir=tmpdir, dry_run=True)
            _run(runner.run_experiment(local_cfg))
            _run(runner.run_experiment(cloud_cfg))

            writer = ResultWriter(tmpdir)
            index = writer.load_index()
            assert len(index) == 2
            names = {r["config_name"] for r in index}
            assert "baseline-local" in names
            assert "baseline-cloud" in names


# ---------------------------------------------------------------------------
# Test 3 — Results JSONL schema validation
# ---------------------------------------------------------------------------


class TestResultsJsonlSchema:
    """Ensure persisted JSONL conforms to the expected schema."""

    def test_results_jsonl_schema_valid(self) -> None:
        """All required top-level and metrics sub-keys must be present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = ResultWriter(tmpdir)
            trials = [
                (0, TrialMetrics(latency_ms=120.0, component_latencies={"stt": 10.0, "llm": 80.0, "tts": 30.0}, token_usage={"prompt": 40, "completion": 20}, success=True, throughput=8.3)),
            ]
            run_id, results_file = writer.write_run("schema-test", trials)

            with open(results_file) as f:
                obj = json.loads(f.readline())

            assert obj["run_id"] == run_id
            assert obj["trial_index"] == 0
            assert obj["metrics"]["latency_ms"] == 120.0
            assert obj["metrics"]["component_latencies"]["llm"] == 80.0
            assert obj["metrics"]["token_usage"]["prompt"] == 40
            assert obj["metrics"]["success"] is True


# ---------------------------------------------------------------------------
# Test 4 — Index CSV is created and populated
# ---------------------------------------------------------------------------


class TestIndexCsvCreated:
    """Validate that index.csv is created and contains the correct summary."""

    def test_index_csv_created_after_run(self) -> None:
        """index.csv must exist and have a data row after a completed run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = ResultWriter(tmpdir)
            trials = [
                (0, TrialMetrics(latency_ms=200.0, success=True, throughput=5.0)),
                (1, TrialMetrics(latency_ms=300.0, success=True, throughput=3.3)),
            ]
            writer.write_run("index-test", trials)

            index_path = Path(tmpdir) / "index.csv"
            assert index_path.exists()

            with open(index_path) as f:
                rows = list(csv.DictReader(f))

            assert len(rows) == 1
            assert rows[0]["config_name"] == "index-test"
            assert float(rows[0]["avg_latency_ms"]) == 250.0
            assert float(rows[0]["success_rate"]) == 1.0
            assert int(rows[0]["total_trials"]) == 2


# ---------------------------------------------------------------------------
# Test 5 — Failed trial is captured and reported
# ---------------------------------------------------------------------------


class TestFailedTrialCaptured:
    """Ensure failed trials are recorded rather than silently dropped."""

    def test_failed_trial_captured_in_jsonl(self) -> None:
        """A TrialMetrics with success=False must be persisted with its error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = ResultWriter(tmpdir)
            trials = [
                (0, TrialMetrics(latency_ms=0.0, success=False, error_message="connection timeout")),
                (1, TrialMetrics(latency_ms=150.0, success=True)),
            ]
            run_id, results_file = writer.write_run("failure-test", trials)

            with open(results_file) as f:
                lines = [json.loads(l) for l in f if l.strip()]

            assert len(lines) == 2

            failed = next(l for l in lines if not l["metrics"]["success"])
            assert failed["metrics"]["error_message"] == "connection timeout"
            assert failed["metrics"]["latency_ms"] == 0.0

    def test_failed_trial_lowers_success_rate_in_index(self) -> None:
        """A mixed run's index.csv row must reflect the partial failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = ResultWriter(tmpdir)
            trials = [
                (0, TrialMetrics(latency_ms=0.0, success=False, error_message="timeout")),
                (1, TrialMetrics(latency_ms=100.0, success=True)),
            ]
            writer.write_run("mixed-test", trials)

            index = writer.load_index()
            assert float(index[0]["success_rate"]) == 0.5


# ---------------------------------------------------------------------------
# Test 6 — System metrics capture
# ---------------------------------------------------------------------------


class TestSystemMetricsCapture:
    """Validate capture_system_metrics() returns sensible values."""

    def test_capture_system_metrics_returns_dict(self) -> None:
        """capture_system_metrics must return a dict with CPU and memory keys."""
        metrics = capture_system_metrics()
        # psutil is in requirements.txt so this should always succeed
        assert isinstance(metrics, dict)
        if metrics:  # empty if psutil missing
            assert "cpu_percent" in metrics
            assert "memory_rss_mb" in metrics
            assert "memory_percent" in metrics
            assert isinstance(metrics["cpu_percent"], float)
            assert metrics["memory_rss_mb"] > 0

    def test_capture_system_metrics_gpu_fields_present(self) -> None:
        """GPU fields must be present (may be None on CPU-only machines)."""
        metrics = capture_system_metrics()
        if metrics:
            assert "gpu_percent" in metrics
            assert "gpu_memory_percent" in metrics
            # Value is None on non-GPU hosts — just confirm the key exists


# ---------------------------------------------------------------------------
# Test 7 — Component latency helpers
# ---------------------------------------------------------------------------


class TestComponentLatencies:
    """Validate ComponentTimer and capture_component_latencies()."""

    def test_component_timer_records_timing(self) -> None:
        """ComponentTimer.measure() must record a non-negative millisecond value."""
        import time

        timer = ComponentTimer()
        with timer.measure("llm"):
            time.sleep(0.01)  # 10 ms

        timings = timer.timings()
        assert "llm" in timings
        assert timings["llm"] >= 10.0  # at least 10 ms

    def test_component_timer_multiple_stages(self) -> None:
        """Multiple measure() calls must produce independent timings."""
        timer = ComponentTimer()
        with timer.measure("stt"):
            pass
        with timer.measure("llm"):
            pass
        with timer.measure("tts"):
            pass

        t = timer.timings()
        assert set(t.keys()) == {"stt", "llm", "tts"}
        for v in t.values():
            assert v >= 0.0

    def test_capture_component_latencies_dict(self) -> None:
        """capture_component_latencies returns correct keys and values."""
        result = capture_component_latencies(stt_ms=12.5, llm_ms=300.0, tts_ms=85.0)
        assert result == {"stt": 12.5, "llm": 300.0, "tts": 85.0}

    def test_capture_component_latencies_defaults_zero(self) -> None:
        """All fields default to 0.0 when not provided."""
        result = capture_component_latencies()
        assert result["stt"] == 0.0
        assert result["llm"] == 0.0
        assert result["tts"] == 0.0


# ---------------------------------------------------------------------------
# Test 8 — OTel export gracefully handles missing endpoint
# ---------------------------------------------------------------------------


class TestOtelExport:
    """Validate export_to_otel() behaviour without a real OTel endpoint."""

    def test_export_to_otel_returns_false_without_endpoint(self) -> None:
        """export_to_otel must return False and not raise when no endpoint is set."""
        import os

        # Ensure the env var is unset for this test
        env_backup = os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        try:
            result = export_to_otel(
                run_id="test-run-001",
                config_name="baseline-cloud",
                summary={"avg_latency_ms": 145.3, "success_rate": 1.0},
                endpoint=None,
            )
            assert result is False
        finally:
            if env_backup is not None:
                os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = env_backup

    def test_export_to_otel_returns_false_without_sdk(self) -> None:
        """export_to_otel must return False gracefully when OTel SDK is absent."""
        import unittest.mock as mock

        # Simulate the SDK not being installed by making the import fail
        with mock.patch.dict("sys.modules", {"opentelemetry": None, "opentelemetry.metrics": None}):
            result = export_to_otel(
                run_id="test-run-002",
                config_name="baseline-local",
                summary={"avg_latency_ms": 800.0, "success_rate": 0.9},
                endpoint="http://localhost:4318",
            )
            assert result is False
