"""Unit tests for benchmark comparison tool."""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

import pytest

_BENCH_ROOT = Path(__file__).parent.parent
_RUNNER_DIR = Path(__file__).parent

if str(_BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BENCH_ROOT))
if str(_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNNER_DIR))

from runner.compare import BenchmarkComparison  # noqa: E402


def _write_index(results_dir: Path, rows: list[dict]) -> Path:
    """Helper: write index.csv with given rows."""
    index_file = results_dir / "index.csv"
    if not rows:
        return index_file
    with open(index_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return index_file


class TestBenchmarkComparisonInit:
    """Test BenchmarkComparison initialization."""

    def test_default_results_dir(self) -> None:
        comparison = BenchmarkComparison()
        assert comparison.results_dir == Path("benchmarks/results")
        assert comparison.index_file == Path("benchmarks/results") / "index.csv"

    def test_custom_results_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            comparison = BenchmarkComparison(results_dir=tmpdir)
            assert str(comparison.results_dir) == tmpdir


class TestLoadIndex:
    """Test load_index method."""

    def test_load_index_returns_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "abc123", "config_name": "test-a", "avg_latency_ms": "100.0", "success_rate": "1.0", "total_trials": "3"},
                {"run_id": "def456", "config_name": "test-b", "avg_latency_ms": "200.0", "success_rate": "0.5", "total_trials": "2"},
            ]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            loaded = comparison.load_index()
            assert len(loaded) == 2
            assert loaded[0]["run_id"] == "abc123"
            assert loaded[1]["run_id"] == "def456"

    def test_load_index_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            comparison = BenchmarkComparison(results_dir=tmpdir)
            loaded = comparison.load_index()
            assert loaded == []

    def test_load_index_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            index_file = Path(tmpdir) / "index.csv"
            index_file.write_text("")
            comparison = BenchmarkComparison(results_dir=tmpdir)
            loaded = comparison.load_index()
            assert loaded == []

    def test_load_index_headers_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_index(Path(tmpdir), [])
            comparison = BenchmarkComparison(results_dir=tmpdir)
            loaded = comparison.load_index()
            assert loaded == []


class TestFilterRuns:
    """Test filter_runs method."""

    def test_no_filter_returns_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "r1", "config_name": "cfg-a"},
                {"run_id": "r2", "config_name": "cfg-b"},
                {"run_id": "r3", "config_name": "cfg-a"},
            ]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            result = comparison.filter_runs()
            assert len(result) == 3

    def test_filter_by_config_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "r1", "config_name": "cfg-a"},
                {"run_id": "r2", "config_name": "cfg-b"},
                {"run_id": "r3", "config_name": "cfg-a"},
            ]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            result = comparison.filter_runs(config_name="cfg-a")
            assert len(result) == 2
            assert all(r["config_name"] == "cfg-a" for r in result)

    def test_filter_by_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "r1", "config_name": "cfg-a"},
                {"run_id": "r2", "config_name": "cfg-a"},
                {"run_id": "r3", "config_name": "cfg-a"},
            ]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            result = comparison.filter_runs(limit=2)
            assert len(result) == 2
            assert result[0]["run_id"] == "r2"
            assert result[1]["run_id"] == "r3"

    def test_filter_by_config_and_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "r1", "config_name": "cfg-a"},
                {"run_id": "r2", "config_name": "cfg-b"},
                {"run_id": "r3", "config_name": "cfg-a"},
                {"run_id": "r4", "config_name": "cfg-a"},
            ]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            result = comparison.filter_runs(config_name="cfg-a", limit=2)
            assert len(result) == 2
            assert result[0]["run_id"] == "r3"
            assert result[1]["run_id"] == "r4"

    def test_filter_no_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"run_id": "r1", "config_name": "cfg-a"}]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            result = comparison.filter_runs(config_name="nonexistent")
            assert result == []

    def test_filter_empty_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            comparison = BenchmarkComparison(results_dir=tmpdir)
            result = comparison.filter_runs(config_name="cfg-a")
            assert result == []

    def test_limit_greater_than_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"run_id": "r1", "config_name": "cfg-a"}, {"run_id": "r2", "config_name": "cfg-a"}]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            result = comparison.filter_runs(limit=100)
            assert len(result) == 2


class TestGenerateCsvComparison:
    """Test generate_csv_comparison method."""

    def test_creates_csv_with_all_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "abc", "config_name": "exp-a", "timestamp": "2025-01-01T00:00:00",
                 "avg_latency_ms": "100.0", "min_latency_ms": "50.0", "max_latency_ms": "150.0",
                 "success_rate": "1.0", "total_trials": "3", "throughput_avg": "10.0",
                 "path_to_results": "/tmp/results/abc/results.jsonl"},
            ]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            output_file = Path(tmpdir) / "comparison.csv"
            comparison.generate_csv_comparison(output_file=output_file)

            assert output_file.exists()
            with open(output_file) as f:
                reader = csv.DictReader(f)
                out_rows = list(reader)
            assert len(out_rows) == 1
            assert out_rows[0]["run_id"] == "abc"
            assert out_rows[0]["config_name"] == "exp-a"
            assert out_rows[0]["avg_latency_ms"] == "100.0"

    def test_csv_excludes_non_comparison_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "abc", "config_name": "exp-a", "timestamp": "2025-01-01T00:00:00",
                 "avg_latency_ms": "100.0", "min_latency_ms": "50.0", "max_latency_ms": "150.0",
                 "success_rate": "1.0", "total_trials": "3", "throughput_avg": "10.0",
                 "path_to_results": "/tmp/results/abc/results.jsonl"},
            ]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            output_file = Path(tmpdir) / "comparison.csv"
            comparison.generate_csv_comparison(output_file=output_file)

            with open(output_file) as f:
                reader = csv.DictReader(f)
                out_rows = list(reader)
            assert "path_to_results" not in out_rows[0]

    def test_csv_with_config_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "r1", "config_name": "cfg-a", "avg_latency_ms": "100.0",
                 "success_rate": "1.0", "total_trials": "1"},
                {"run_id": "r2", "config_name": "cfg-b", "avg_latency_ms": "200.0",
                 "success_rate": "0.5", "total_trials": "2"},
            ]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            output_file = Path(tmpdir) / "comparison.csv"
            comparison.generate_csv_comparison(output_file=output_file, config_name="cfg-a")

            with open(output_file) as f:
                out_rows = list(csv.DictReader(f))
            assert len(out_rows) == 1
            assert out_rows[0]["config_name"] == "cfg-a"

    def test_csv_empty_no_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            comparison = BenchmarkComparison(results_dir=tmpdir)
            output_file = Path(tmpdir) / "comparison.csv"
            comparison.generate_csv_comparison(output_file=output_file)
            assert not output_file.exists()

    def test_csv_creates_parent_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "abc", "config_name": "exp-a", "avg_latency_ms": "100.0",
                 "success_rate": "1.0", "total_trials": "1"},
            ]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            nested = Path(tmpdir) / "subdir" / "nested" / "comparison.csv"
            comparison.generate_csv_comparison(output_file=nested)
            assert nested.exists()


class TestGenerateTextSummary:
    """Test generate_text_summary method."""

    def test_summary_with_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "abc123", "config_name": "exp-a", "avg_latency_ms": "100.0",
                 "success_rate": "1.0", "total_trials": "3"},
            ]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            summary = comparison.generate_text_summary()
            assert "Benchmark Comparison Summary" in summary
            assert "abc123" in summary
            assert "100.00" in summary
            assert "%" in summary
            assert "3" in summary

    def test_summary_no_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            comparison = BenchmarkComparison(results_dir=tmpdir)
            summary = comparison.generate_text_summary()
            assert summary == "No runs found."

    def test_summary_with_config_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "r1", "config_name": "cfg-a", "avg_latency_ms": "50.0",
                 "success_rate": "1.0", "total_trials": "1"},
            ]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            summary = comparison.generate_text_summary(config_name="cfg-a")
            assert "Config: cfg-a" in summary

    def test_summary_with_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "r1", "config_name": "cfg-a", "avg_latency_ms": "10.0",
                 "success_rate": "1.0", "total_trials": "1"},
                {"run_id": "r2", "config_name": "cfg-a", "avg_latency_ms": "20.0",
                 "success_rate": "0.5", "total_trials": "2"},
            ]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            summary = comparison.generate_text_summary(limit=1)
            assert "r1" not in summary
            assert "r2" in summary


class TestPrintSummary:
    """Test print_summary method."""

    def test_print_summary_output(self, capsys: pytest.CaptureFixture) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"run_id": "abc", "config_name": "exp-a", "avg_latency_ms": "100.0",
                 "success_rate": "1.0", "total_trials": "3"},
            ]
            _write_index(Path(tmpdir), rows)
            comparison = BenchmarkComparison(results_dir=tmpdir)
            comparison.print_summary()
            captured = capsys.readouterr()
            assert "Benchmark Comparison Summary" in captured.out

    def test_print_summary_empty(self, capsys: pytest.CaptureFixture) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            comparison = BenchmarkComparison(results_dir=tmpdir)
            comparison.print_summary()
            captured = capsys.readouterr()
            assert "No runs found." in captured.out
