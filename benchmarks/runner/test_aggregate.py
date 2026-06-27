"""Tests for the benchmark aggregator — issue #68."""

from __future__ import annotations

import csv
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

from aggregate import BenchmarkAggregator, _INDEX_COLUMNS  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_row(
    run_id: str,
    config_label: str,
    category: str,
    status: str,
    latency_total: float | None,
    expects_tool: bool,
    expected_tool_type: str | None,
    tool_was_invoked: bool,
    invoked_tool_type: str | None,
    result_incorporated_in_reply: bool | None = None,
    path: str = "text",
) -> dict:
    return {
        "run_id": run_id,
        "timestamp": "2026-06-25T12:00:00Z",
        "run_number": 1,
        "config_label": config_label,
        "config": {
            "stt_provider": "deepgram",
            "stt_model": "nova-3",
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "tts_provider": "elevenlabs",
            "tts_voice_id": "voice1",
            "tts_model": "eleven_multilingual_v2",
        },
        "prompt": {
            "category": category,
            "id": f"{category}_01",
            "text": "test prompt",
            "expects_tool": expects_tool,
            "expected_tool_type": expected_tool_type,
        },
        "path": path,
        "turn_index": 0,
        "turn_count": 1,
        "latency_ms": {
            "stt_processing": None,
            "llm_call": 80.0 if latency_total is not None else None,
            "llm_api": None,
            "tool_call": None,
            "tts_synthesis": None,
            "total": latency_total,
            "voice_turn": None,
            "cumulative_total": None,
        },
        "tool_reliability": {
            "tool_was_invoked": tool_was_invoked,
            "invoked_tool_type": invoked_tool_type,
            "correct_tool_selected": None,
            "result_incorporated_in_reply": result_incorporated_in_reply,
        },
        "status": status,
        "error": None if status != "error" else "test error",
    }


def _write_jsonl(component_dir: Path, rows: list[dict]) -> Path:
    """Write rows to a single JSONL file in component_dir."""
    component_dir.mkdir(parents=True, exist_ok=True)
    path = component_dir / "2026-06-25T12-00-00_component_benchmark.jsonl"
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return path


def _fixture_rows() -> list[dict]:
    """Two configs, 5 rows total: one failure, one null-latency row."""
    return [
        # cfg-alpha — 3 rows: 2 success with latency, 1 error with null latency
        _make_row("run-1", "cfg-alpha", "short_no_tool", "success", 100.0,
                  False, None, False, None),
        _make_row("run-1", "cfg-alpha", "short_with_tool", "success", 100.0,
                  True, "agent_transfer", True, "agent_transfer"),
        _make_row("run-1", "cfg-alpha", "short_no_tool", "error", None,
                  False, None, False, None),
        # cfg-beta — 2 rows: both success with latency
        _make_row("run-1", "cfg-beta", "short_no_tool", "success", 200.0,
                  False, None, False, None),
        _make_row("run-1", "cfg-beta", "short_with_tool", "success", 300.0,
                  True, "agent_transfer", True, "agent_transfer"),
    ]


# ---------------------------------------------------------------------------
# index.csv structure
# ---------------------------------------------------------------------------


def test_index_csv_has_all_columns() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        _write_jsonl(results_dir / "component", _fixture_rows())

        aggregator = BenchmarkAggregator(results_dir=results_dir)
        aggregator.write_index_csv()

        with open(results_dir / "index.csv") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == _INDEX_COLUMNS


def test_index_csv_includes_model_and_path_columns() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        _write_jsonl(results_dir / "component", _fixture_rows())

        aggregator = BenchmarkAggregator(results_dir=results_dir)
        aggregator.write_index_csv()

        with open(results_dir / "index.csv") as fh:
            row = next(csv.DictReader(fh))

        assert row["path"] == "text"
        assert row["stt_model"] == "nova-3"
        assert row["llm_model"] == "gpt-4o-mini"
        assert row["tts_model"] == "eleven_multilingual_v2"


def test_index_csv_separates_text_and_voice_paths() -> None:
    rows = [
        _make_row("run-1", "cfg-alpha", "short_no_tool", "success", 100.0,
                  False, None, False, None, path="text"),
        _make_row("run-1", "cfg-alpha", "short_no_tool", "success", 400.0,
                  False, None, False, None, path="voice"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        _write_jsonl(results_dir / "component", rows)
        aggregator = BenchmarkAggregator(results_dir=results_dir)
        aggregator.write_index_csv()

        with open(results_dir / "index.csv") as fh:
            csv_rows = list(csv.DictReader(fh))

        assert len(csv_rows) == 2
        paths = {r["path"] for r in csv_rows}
        assert paths == {"text", "voice"}
        voice_row = next(r for r in csv_rows if r["path"] == "voice")
        assert float(voice_row["avg_latency_ms"]) == 400.0


def test_index_csv_has_one_row_per_config() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        _write_jsonl(results_dir / "component", _fixture_rows())

        aggregator = BenchmarkAggregator(results_dir=results_dir)
        aggregator.write_index_csv()

        with open(results_dir / "index.csv") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 2
        assert rows[0]["config_name"] == "cfg-alpha"
        assert rows[1]["config_name"] == "cfg-beta"


# ---------------------------------------------------------------------------
# index.csv computed values
# ---------------------------------------------------------------------------

# cfg-alpha fixture:
#   latency totals = [100.0, 100.0]  (null-latency error row excluded)
#   success = 2, fail = 1, total = 3
#   avg = 100.0, min = 100.0, max = 100.0
#   success_rate = 2/3
#   throughput = 2 / (200ms / 1000) = 10.0


def test_index_csv_cfg_alpha_latency() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        _write_jsonl(results_dir / "component", _fixture_rows())
        aggregator = BenchmarkAggregator(results_dir=results_dir)
        aggregator.write_index_csv()

        with open(results_dir / "index.csv") as fh:
            row = next(r for r in csv.DictReader(fh) if r["config_name"] == "cfg-alpha")

        assert float(row["avg_latency_ms"]) == 100.0
        assert float(row["min_latency_ms"]) == 100.0
        assert float(row["max_latency_ms"]) == 100.0


def test_index_csv_cfg_alpha_counts_and_rate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        _write_jsonl(results_dir / "component", _fixture_rows())
        aggregator = BenchmarkAggregator(results_dir=results_dir)
        aggregator.write_index_csv()

        with open(results_dir / "index.csv") as fh:
            row = next(r for r in csv.DictReader(fh) if r["config_name"] == "cfg-alpha")

        assert int(row["total_trials"]) == 3
        assert int(row["failure_count"]) == 1
        assert abs(float(row["success_rate"]) - 2 / 3) < 0.0001
        assert abs(float(row["throughput_avg"]) - 10.0) < 0.0001


# cfg-beta fixture:
#   latency totals = [200.0, 300.0]
#   success = 2, fail = 0, total = 2
#   avg = 250.0, min = 200.0, max = 300.0
#   success_rate = 1.0
#   throughput = 2 / (500ms / 1000) = 4.0


def test_index_csv_cfg_beta_computed_values() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        _write_jsonl(results_dir / "component", _fixture_rows())
        aggregator = BenchmarkAggregator(results_dir=results_dir)
        aggregator.write_index_csv()

        with open(results_dir / "index.csv") as fh:
            row = next(r for r in csv.DictReader(fh) if r["config_name"] == "cfg-beta")

        assert float(row["avg_latency_ms"]) == 250.0
        assert float(row["min_latency_ms"]) == 200.0
        assert float(row["max_latency_ms"]) == 300.0
        assert int(row["total_trials"]) == 2
        assert int(row["failure_count"]) == 0
        assert float(row["success_rate"]) == 1.0
        assert abs(float(row["throughput_avg"]) - 4.0) < 0.0001


def test_null_latency_rows_excluded_from_averages() -> None:
    # The cfg-alpha error row has null latency — avg/min/max must ignore it.
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        _write_jsonl(results_dir / "component", _fixture_rows())
        aggregator = BenchmarkAggregator(results_dir=results_dir)
        aggregator.write_index_csv()

        with open(results_dir / "index.csv") as fh:
            row = next(r for r in csv.DictReader(fh) if r["config_name"] == "cfg-alpha")

        # If null were treated as 0 the avg would be < 100; must stay at 100.
        assert float(row["avg_latency_ms"]) == 100.0
        assert float(row["min_latency_ms"]) > 0.0


# ---------------------------------------------------------------------------
# Component report
# ---------------------------------------------------------------------------


def test_generate_component_report_contains_both_configs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        _write_jsonl(results_dir / "component", _fixture_rows())
        aggregator = BenchmarkAggregator(results_dir=results_dir)
        report = aggregator.generate_component_report()

        assert "cfg-alpha" in report
        assert "cfg-beta" in report


def test_generate_component_report_contains_category_names() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        _write_jsonl(results_dir / "component", _fixture_rows())
        aggregator = BenchmarkAggregator(results_dir=results_dir)
        report = aggregator.generate_component_report()

        assert "short_no_tool" in report
        assert "short_with_tool" in report


def test_generate_component_report_contains_reliability_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        _write_jsonl(results_dir / "component", _fixture_rows())
        aggregator = BenchmarkAggregator(results_dir=results_dir)
        report = aggregator.generate_component_report()

        assert "Reliability (authoritative)" in report
        assert "reliability_rate" in report


def test_generate_component_report_skips_all_null_stages() -> None:
    # stt_processing and tts_synthesis are always null on the text path;
    # they must not appear in the stage latency section.
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        _write_jsonl(results_dir / "component", _fixture_rows())
        aggregator = BenchmarkAggregator(results_dir=results_dir)
        report = aggregator.generate_component_report()

        assert "stt_processing" not in report
        assert "tts_synthesis" not in report
        assert "llm_call" in report  # non-null stage is present


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_aggregator_empty_component_dir_produces_empty_index() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        (results_dir / "component").mkdir()
        aggregator = BenchmarkAggregator(results_dir=results_dir)
        aggregator.write_index_csv()

        with open(results_dir / "index.csv") as fh:
            rows = list(csv.DictReader(fh))
        assert rows == []


def test_aggregator_missing_component_dir_returns_empty_rows() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        aggregator = BenchmarkAggregator(results_dir=Path(tmp))
        rows = aggregator.load_jsonl_rows()
        assert rows == []


def test_write_index_csv_accepts_pre_loaded_rows() -> None:
    # write_index_csv(rows=...) must not re-read from disk.
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        rows = _fixture_rows()[:2]  # only cfg-alpha success rows
        aggregator = BenchmarkAggregator(results_dir=results_dir)
        aggregator.write_index_csv(rows=rows)

        with open(results_dir / "index.csv") as fh:
            csv_rows = list(csv.DictReader(fh))
        assert len(csv_rows) == 1
        assert csv_rows[0]["config_name"] == "cfg-alpha"
