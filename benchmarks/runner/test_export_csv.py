"""Tests for readable CSV export (#68)."""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

_RUNNER_DIR = Path(__file__).parent
if str(_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNNER_DIR))

from aggregate import BenchmarkAggregator, _row_succeeded
from export_csv import build_export_rows


def _voice_row(
    config_label: str,
    category: str,
    total: float,
    *,
    status: str = "success",
    stt: float | None = 100.0,
    llm: float | None = 200.0,
    tts: float | None = 150.0,
) -> dict:
    return {
        "run_id": f"run-{category}",
        "config_label": config_label,
        "path": "voice",
        "status": status,
        "config": {
            "stt_provider": "deepgram",
            "stt_model": "nova-3",
            "llm_provider": "openai" if "cloud" in config_label else "ollama",
            "llm_model": "gpt-4o-mini" if "cloud" in config_label else "gemma4:26b",
            "tts_provider": "elevenlabs" if "cloud" in config_label else "deepgram",
            "tts_voice_id": "voice",
            "tts_model": "model",
        },
        "prompt": {
            "category": category,
            "id": f"{category}_01",
            "expects_tool": False,
            "expected_tool_type": None,
            "expected_status": "success",
        },
        "latency_ms": {
            "stt_processing": stt,
            "llm_call": llm,
            "tool_call": 1.0,
            "tts_synthesis": tts,
            "total": total,
        },
        "tool_reliability": {
            "tool_was_invoked": False,
            "invoked_tool_type": None,
            "correct_tool_selected": True,
            "result_incorporated_in_reply": None,
        },
    }


def test_export_has_overall_and_category_sections() -> None:
    rows = [
        _voice_row("cloud-openai-deepgram-elevenlabs", "short_no_tool", 2500.0),
        _voice_row("cloud-openai-deepgram-elevenlabs", "short_with_tool", 2700.0),
        _voice_row("oss-ollama-deepgram-deepgram", "short_no_tool", 9000.0),
    ]
    export = build_export_rows(rows, row_succeeded_fn=_row_succeeded)
    sections = {r["Section"] for r in export}
    assert sections == {"Overall", "By category"}
    overall = [r for r in export if r["Section"] == "Overall"]
    assert len(overall) == 2
    cloud = next(r for r in overall if r["Configuration"].startswith("Cloud"))
    assert cloud["Total avg (ms)"] == "2,600.0"
    assert cloud["Recommended"] in {"Yes", "No"}
    by_cat = [r for r in export if r["Section"] == "By category"]
    assert len(by_cat) == 3
    assert by_cat[0]["Category"] in {"short_no_tool", "short_with_tool"}


def test_aggregator_writes_single_summary_csv() -> None:
    rows = [
        _voice_row("cloud-openai-deepgram-elevenlabs", "short_no_tool", 2500.0),
        _voice_row("oss-ollama-deepgram-deepgram", "short_no_tool", 9000.0),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        aggregator = BenchmarkAggregator(results_dir=tmp)
        summary_path = aggregator.write_readable_csv_export(rows)
        assert summary_path.name == "benchmark-summary.csv"
        assert not (Path(tmp) / "benchmark-by-category.csv").exists()
        with open(summary_path, encoding="utf-8") as fh:
            csv_rows = list(csv.DictReader(fh))
        assert len(csv_rows) == 4
        assert csv_rows[0]["Section"] == "Overall"
        assert csv_rows[0]["STT (ms)"] == "100.0"


def test_by_category_reliability_matches_authoritative_summary() -> None:
    passing = _voice_row("oss-ollama-deepgram-deepgram", "long_with_tool", 5000.0)
    failing = _voice_row("oss-ollama-deepgram-deepgram", "long_with_tool", 5100.0)

    for row, incorporated in ((passing, True), (failing, False)):
        row["prompt"]["expects_tool"] = True
        row["prompt"]["expected_tool_type"] = "data_extraction"
        row["tool_reliability"] = {
            "tool_was_invoked": True,
            "invoked_tool_type": "data_extraction",
            "correct_tool_selected": True,
            "result_incorporated_in_reply": incorporated,
        }

    export = build_export_rows([passing, failing], row_succeeded_fn=_row_succeeded)

    by_category = next(
        row
        for row in export
        if row["Section"] == "By category"
        and row["Configuration"] == "OSS (Ollama + Deepgram)"
        and row["Path"] == "voice"
        and row["Category"] == "long_with_tool"
    )
    assert by_category["Tool reliability"] == "50.0%"
