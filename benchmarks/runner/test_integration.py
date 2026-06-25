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
                assert isinstance(obj["metrics"]["system_metrics"], dict)


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
            assert isinstance(obj["metrics"]["system_metrics"], dict)


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


class TestInvalidConfig:
    """Validate run_experiment rejects invalid configurations."""

    def test_run_experiment_raises_on_invalid_config(self) -> None:
        """An ExperimentConfig failing validate() must raise ValueError."""
        invalid_cfg = ExperimentConfig(
            name="bad",
            description="",
            provider="local",
            model="test",
            input_set="test.jsonl",
            repetitions=0,
            concurrency=0,
            metrics=[],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(results_dir=tmpdir, dry_run=True)
            with pytest.raises(ValueError, match="Invalid config"):
                _run(runner.run_experiment(invalid_cfg))

    def test_run_experiment_raises_on_empty_metrics(self) -> None:
        """Config with empty metrics list must raise ValueError."""
        cfg = ExperimentConfig(
            name="no-metrics",
            description="",
            provider="openai",
            model="gpt-4o",
            input_set="test.jsonl",
            repetitions=1,
            concurrency=1,
            metrics=[],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(results_dir=tmpdir, dry_run=True)
            with pytest.raises(ValueError, match="Invalid config"):
                _run(runner.run_experiment(cfg))


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


# ---------------------------------------------------------------------------
# Test 9 — Real _execute_trial with mocked HTTP (no live backend needed)
# ---------------------------------------------------------------------------


class TestExecuteTrial:
    """Validate _execute_trial() sends the right payload and records real latency."""

    def _make_config(self, provider: str = "openai", model: str = "gpt-4o-mini") -> ExperimentConfig:
        return ExperimentConfig(
            name="trial-test",
            description="",
            provider=provider,
            model=model,
            input_set="benchmarks/inputs/short_prompts.jsonl",
            repetitions=1,
            concurrency=1,
            metrics=["latency_e2e"],
            timeout_seconds=10,
        )

    def test_execute_trial_success(self) -> None:
        """A 200 response must produce a successful TrialMetrics with real latency."""
        import unittest.mock as mock
        import httpx

        mock_response = mock.MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "conversation_id": "conv-abc",
            "reply": {"role": "assistant", "content": "You have 3 tasks due today."},
            "status": "success",
        }

        config = self._make_config()
        input_data = [{"input": "What tasks do I have today?", "expected_type": "task_query"}]

        with mock.patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock.AsyncMock()
            mock_client.post = mock.AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = mock.AsyncMock(return_value=False)

            with tempfile.TemporaryDirectory() as tmpdir:
                runner = BenchmarkRunner(results_dir=tmpdir, dry_run=False)
                metrics = _run(runner._execute_trial(config, trial_idx=0, input_data=input_data))

        assert metrics.success is True
        assert metrics.latency_ms >= 0.0
        assert metrics.throughput > 0.0

        # Verify the payload sent to the backend
        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
        assert payload["agent_config"]["llm"]["provider"] == "openai"
        assert payload["agent_config"]["llm"]["model"] == "gpt-4o-mini"
        assert payload["messages"][0]["content"] == "What tasks do I have today?"

    def test_execute_trial_http_error_captured(self) -> None:
        """A non-200 response must produce a failed TrialMetrics with the error body."""
        import unittest.mock as mock
        import httpx

        mock_response = mock.MagicMock(spec=httpx.Response)
        mock_response.status_code = 422
        mock_response.text = '{"detail": "provider openrouter not supported"}'

        config = self._make_config(provider="openrouter", model="qwen/qwen3-next-80b-a3b-instruct:free")

        with mock.patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock.AsyncMock()
            mock_client.post = mock.AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = mock.AsyncMock(return_value=False)

            with tempfile.TemporaryDirectory() as tmpdir:
                runner = BenchmarkRunner(results_dir=tmpdir, dry_run=False)
                metrics = _run(runner._execute_trial(config, trial_idx=0))

        assert metrics.success is False
        assert "422" in metrics.error_message

    def test_execute_trial_connection_error_captured(self) -> None:
        """A ConnectError (backend not running) must produce a failed TrialMetrics."""
        import unittest.mock as mock
        import httpx

        config = self._make_config()

        with mock.patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock.AsyncMock()
            mock_client.post = mock.AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client_cls.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = mock.AsyncMock(return_value=False)

            with tempfile.TemporaryDirectory() as tmpdir:
                runner = BenchmarkRunner(results_dir=tmpdir, dry_run=False)
                metrics = _run(runner._execute_trial(config, trial_idx=0))

        assert metrics.success is False
        assert "connect" in metrics.error_message.lower()

    def test_execute_trial_cycles_input_prompts(self) -> None:
        """trial_idx should cycle through input_data so each trial gets a different prompt."""
        import unittest.mock as mock
        import httpx

        captured_payloads: list[dict] = []

        async def fake_post(url: str, **kwargs: Any) -> httpx.Response:
            captured_payloads.append(kwargs.get("json", {}))
            resp = mock.MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"reply": {"content": "ok"}, "status": "success"}
            return resp

        input_data = [
            {"input": "First prompt", "expected_type": "a"},
            {"input": "Second prompt", "expected_type": "b"},
        ]
        config = self._make_config()

        with mock.patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock.AsyncMock()
            mock_client.post = fake_post
            mock_client_cls.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = mock.AsyncMock(return_value=False)

            with tempfile.TemporaryDirectory() as tmpdir:
                runner = BenchmarkRunner(results_dir=tmpdir, dry_run=False)
                _run(runner._execute_trial(config, 0, input_data))
                _run(runner._execute_trial(config, 1, input_data))
                _run(runner._execute_trial(config, 2, input_data))  # wraps to index 0

        assert captured_payloads[0]["messages"][0]["content"] == "First prompt"
        assert captured_payloads[1]["messages"][0]["content"] == "Second prompt"
        assert captured_payloads[2]["messages"][0]["content"] == "First prompt"  # cycled

    def test_execute_trial_openrouter_provider_mapped_correctly(self) -> None:
        """provider=openrouter in config must reach the backend as 'openrouter', not 'openai'."""
        import unittest.mock as mock
        import httpx

        captured: list[dict] = []

        async def fake_post(url: str, **kwargs: Any) -> httpx.Response:
            captured.append(kwargs.get("json", {}))
            resp = mock.MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"reply": {"content": "ok"}, "status": "success"}
            return resp

        config = self._make_config(provider="openrouter", model="google/gemma-4-31b-it:free")

        with mock.patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock.AsyncMock()
            mock_client.post = fake_post
            mock_client_cls.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = mock.AsyncMock(return_value=False)

            with tempfile.TemporaryDirectory() as tmpdir:
                runner = BenchmarkRunner(results_dir=tmpdir, dry_run=False)
                _run(runner._execute_trial(config, 0))

        assert captured[0]["agent_config"]["llm"]["provider"] == "openrouter"
        assert captured[0]["agent_config"]["llm"]["model"] == "google/gemma-4-31b-it:free"


class TestBenchmarkConcurrency:
    """Validate that benchmark execution respects the configured concurrency."""

    def test_run_experiment_honors_concurrency_limit(self) -> None:
        """run_experiment should not exceed the configured concurrency."""
        import unittest.mock as mock

        config = ExperimentConfig(
            name="concurrency-test",
            description="",
            provider="openai",
            model="gpt-4o-mini",
            input_set="benchmarks/inputs/short_prompts.jsonl",
            repetitions=3,
            concurrency=2,
            metrics=["latency_e2e"],
            timeout_seconds=10,
        )

        active = 0
        peak_active = 0

        async def fake_execute_trial(*_args, **_kwargs):
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return TrialMetrics(latency_ms=100.0, success=True, throughput=10.0)

        with mock.patch.object(BenchmarkRunner, "_execute_trial", side_effect=fake_execute_trial):
            with tempfile.TemporaryDirectory() as tmpdir:
                runner = BenchmarkRunner(results_dir=tmpdir, dry_run=False)
                _run(runner.run_experiment(config))

        assert peak_active == 2
