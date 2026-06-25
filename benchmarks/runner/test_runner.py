"""Unit tests for benchmark runner modules."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import pytest
import yaml

from benchmarks.runner.config import ExperimentConfig
from benchmarks.runner.storage import ResultWriter, RunMetadata, TrialMetrics


class TestExperimentConfig:
    """Test experiment configuration parsing and validation."""

    def test_valid_config_dict(self) -> None:
        """Test loading valid config from dict."""
        data = {
            "name": "test-exp",
            "provider": "local",
            "model": "test-model",
            "input_set": "tests/inputs/test.jsonl",
            "repetitions": 3,
        }
        config = ExperimentConfig(
            name=data["name"],
            description="",
            provider=data["provider"],
            model=data["model"],
            input_set=data["input_set"],
            repetitions=data["repetitions"],
            concurrency=1,
            metrics=["latency_e2e"],
        )
        assert config.name == "test-exp"
        assert config.provider == "local"

    def test_config_validate_success(self) -> None:
        """Test config validation passes."""
        config = ExperimentConfig(
            name="test",
            description="test config",
            provider="local",
            model="test",
            input_set="test.jsonl",
            repetitions=2,
            concurrency=1,
            metrics=["latency_e2e", "token_usage"],
        )
        is_valid, msg = config.validate()
        assert is_valid
        assert msg == ""

    def test_config_validate_invalid_repetitions(self) -> None:
        """Test validation fails for invalid repetitions."""
        config = ExperimentConfig(
            name="test",
            description="",
            provider="local",
            model="test",
            input_set="test.jsonl",
            repetitions=0,
            concurrency=1,
            metrics=["latency_e2e"],
        )
        is_valid, msg = config.validate()
        assert not is_valid
        assert "repetitions must be >= 1" in msg

    def test_config_validate_invalid_metrics(self) -> None:
        """Test validation fails for invalid metrics."""
        config = ExperimentConfig(
            name="test",
            description="",
            provider="local",
            model="test",
            input_set="test.jsonl",
            repetitions=1,
            concurrency=1,
            metrics=["invalid_metric"],
        )
        is_valid, msg = config.validate()
        assert not is_valid
        assert "Invalid metrics" in msg

    def test_config_to_dict(self) -> None:
        """Test config serialization."""
        config = ExperimentConfig(
            name="test",
            description="desc",
            provider="openai",
            model="gpt-4",
            input_set="test.jsonl",
            repetitions=5,
            concurrency=2,
            metrics=["latency_e2e", "token_usage"],
        )
        d = config.to_dict()
        assert d["name"] == "test"
        assert d["repetitions"] == 5
        assert d["metrics"] == ["latency_e2e", "token_usage"]


    def test_from_yaml_missing_file(self) -> None:
        """from_yaml raises FileNotFoundError for non-existent path."""
        with pytest.raises(FileNotFoundError):
            ExperimentConfig.from_yaml("/nonexistent/path.yaml")

    def test_from_yaml_valid_file(self) -> None:
        """from_yaml parses valid YAML correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"
            config_data = {
                "name": "yaml-test",
                "provider": "openai",
                "model": "gpt-4o",
                "input_set": "inputs/test.jsonl",
                "repetitions": 3,
                "concurrency": 2,
                "metrics": ["latency_e2e", "token_usage"],
            }
            with open(config_path, "w") as f:
                yaml.dump(config_data, f)

            config = ExperimentConfig.from_yaml(config_path)
            assert config.name == "yaml-test"
            assert config.provider == "openai"
            assert config.repetitions == 3
            assert config.concurrency == 2

    def test_from_yaml_missing_required_field(self) -> None:
        """from_yaml raises ValueError when required fields are missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "bad.yaml"
            with open(config_path, "w") as f:
                yaml.dump({"name": "incomplete"}, f)

            with pytest.raises(ValueError, match="Missing required fields"):
                ExperimentConfig.from_yaml(config_path)

    def test_from_yaml_non_dict_yaml(self) -> None:
        """from_yaml raises ValueError when YAML is not a dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "list.yaml"
            with open(config_path, "w") as f:
                yaml.dump(["just", "a", "list"], f)

            with pytest.raises(ValueError, match="Invalid config format"):
                ExperimentConfig.from_yaml(config_path)

    def test_from_yaml_invalid_yaml_syntax(self) -> None:
        """from_yaml raises YAMLError on malformed YAML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "malformed.yaml"
            config_path.write_text(": invalid yaml syntax {{{")

            with pytest.raises(yaml.YAMLError):
                ExperimentConfig.from_yaml(config_path)


class TestTrialMetrics:
    """Test trial metrics data class."""

    def test_trial_metrics_creation(self) -> None:
        """Test creating trial metrics."""
        metrics = TrialMetrics(
            latency_ms=100.5,
            component_latencies={"stt": 10.0, "llm": 50.0},
            token_usage={"prompt": 50, "completion": 25},
            success=True,
            throughput=10.0,
        )
        assert metrics.latency_ms == 100.5
        assert metrics.success is True
        assert metrics.component_latencies["stt"] == 10.0

    def test_trial_metrics_to_dict(self) -> None:
        """Test metrics serialization."""
        metrics = TrialMetrics(
            latency_ms=150.0,
            token_usage={"prompt": 100},
            success=True,
        )
        d = metrics.to_dict()
        assert d["latency_ms"] == 150.0
        assert d["success"] is True
        assert d["token_usage"]["prompt"] == 100


class TestResultWriter:
    """Test result storage and serialization."""

    def test_writer_creates_index(self) -> None:
        """Test that writer creates index.csv."""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = ResultWriter(tmpdir)
            index_file = Path(tmpdir) / "index.csv"
            assert index_file.exists()

            with open(index_file) as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                assert "run_id" in headers
                assert "config_name" in headers

    def test_write_run(self) -> None:
        """Test writing a complete run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = ResultWriter(tmpdir)

            trials = [
                (0, TrialMetrics(latency_ms=100.0, success=True, throughput=10.0)),
                (1, TrialMetrics(latency_ms=105.0, success=True, throughput=9.5)),
            ]

            run_id, results_file = writer.write_run("test-config", trials)

            assert run_id
            assert results_file.exists()

    def test_write_run_populates_runtime_metadata(self) -> None:
        """ResultWriter should fill in environment metadata automatically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = ResultWriter(tmpdir)

            trials = [
                (0, TrialMetrics(latency_ms=100.0, success=True, throughput=10.0)),
            ]

            run_id, results_file = writer.write_run("metadata-test", trials)

            with open(results_file) as f:
                record = json.loads(f.readline())

            environment = record["environment"]
            assert record["run_id"] == run_id
            assert environment["run_id"] == run_id
            assert environment["config_name"] == "metadata-test"
            assert environment["python_version"]
            assert isinstance(environment["dependencies"], dict)

    def test_results_jsonl_format(self) -> None:
        """Test JSONL result format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = ResultWriter(tmpdir)

            trials = [
                (0, TrialMetrics(latency_ms=100.0, token_usage={"prompt": 50}, success=True)),
            ]

            run_id, results_file = writer.write_run("test-config", trials)

            with open(results_file) as f:
                line = f.readline()
                data = json.loads(line)
                assert "run_id" in data
                assert "metrics" in data
                assert data["metrics"]["latency_ms"] == 100.0
                assert data["trial_index"] == 0

    def test_index_csv_summary(self) -> None:
        """Test index.csv summary row."""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = ResultWriter(tmpdir)

            trials = [
                (0, TrialMetrics(latency_ms=100.0, success=True, throughput=10.0)),
                (1, TrialMetrics(latency_ms=200.0, success=True, throughput=5.0)),
            ]

            writer.write_run("test-config", trials)

            index_rows = writer.load_index()
            assert len(index_rows) == 1
            row = index_rows[0]
            assert float(row["avg_latency_ms"]) == 150.0
            assert float(row["success_rate"]) == 1.0

    def test_load_run(self) -> None:
        """Test loading a run by ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = ResultWriter(tmpdir)

            trials = [
                (0, TrialMetrics(latency_ms=100.0, success=True)),
            ]

            run_id, _ = writer.write_run("test-config", trials)

            loaded = writer.load_run(run_id)
            assert len(loaded) == 1
            assert loaded[0]["trial_index"] == 0
            assert loaded[0]["metrics"]["latency_ms"] == 100.0
