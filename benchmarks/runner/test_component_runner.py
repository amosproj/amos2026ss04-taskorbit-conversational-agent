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
from component_config import ComponentBenchmarkConfig, PipelineComponentConfig
from component_runner import ComponentBenchmarkRunner


def test_component_config_loads_yaml() -> None:
    config_path = _BENCH_ROOT / "configs" / "component-benchmark.yaml"
    config = ComponentBenchmarkConfig.from_yaml(config_path)
    assert config.name == "component-benchmark"
    assert len(config.configs) >= 2
    assert "text" in config.paths
    assert "voice" in config.paths
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


def _minimal_prompt() -> dict:
    return {
        "id": "inq_hours_01",
        "category": "short_no_tool",
        "turns": ["What are your business hours?"],
        "expects_tool": False,
        "expected_tool_type": None,
        "expected_status": "success",
        "intent_name": "general_inquiry",
        "agent_template": "general_inquiry",
    }


def _minimal_pipeline(name: str = "cloud-openai-deepgram-elevenlabs") -> PipelineComponentConfig:
    return PipelineComponentConfig(
        name=name,
        stt_provider="deepgram",
        stt_model="nova-3",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        tts_provider="elevenlabs",
        tts_voice_id="CwhRBWXzGAHq8TQ4Fs17",
        tts_model="eleven_multilingual_v2",
    )


def _minimal_config() -> ComponentBenchmarkConfig:
    return ComponentBenchmarkConfig(
        name="component-test",
        description="",
        prompt_set="benchmarks/prompts/component_prompts.json",
        repetitions=1,
        concurrency=1,
        timeout_seconds=10,
        paths=["text"],
        configs=[
            _minimal_pipeline("cfg-a"),
            _minimal_pipeline("cfg-b"),
        ],
    )


def test_run_prompt_case_success_records_latency() -> None:
    """A 200 response must produce a success row with API latency fields."""
    import unittest.mock as mock

    import httpx

    mock_response = mock.MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "conversation_id": "conv-123",
        "reply": {"role": "assistant", "content": "We are open 9 to 5."},
        "status": "success",
        "latency_ms": {"llm_call": 120.0, "tool_call": 5.0, "total": 125.0},
    }

    config = _minimal_config()
    pipeline = config.configs[0]
    prompt_def = _minimal_prompt()

    with mock.patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = mock.AsyncMock()
        mock_client.post = mock.AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        with tempfile.TemporaryDirectory() as tmp:
            runner = ComponentBenchmarkRunner(results_dir=tmp, dry_run=False)
            rows = asyncio.run(
                runner._run_prompt_case(config, pipeline, prompt_def, 1, "text")
            )

    assert len(rows) == 1
    row = rows[0].to_dict()
    assert row["status"] == "success"
    assert row["latency_ms"]["llm_call"] == 120.0
    assert row["latency_ms"]["total"] == 125.0
    assert row["path"] == "text"


def test_run_prompt_case_http_error_stops_turn_loop() -> None:
    """A non-200 response must emit an error row and stop further turns."""
    import unittest.mock as mock

    import httpx

    mock_response = mock.MagicMock(spec=httpx.Response)
    mock_response.status_code = 503
    mock_response.text = "service unavailable"

    config = _minimal_config()
    pipeline = config.configs[0]
    prompt_def = {
        **_minimal_prompt(),
        "turns": ["Turn one", "Turn two"],
    }

    with mock.patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = mock.AsyncMock()
        mock_client.post = mock.AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        with tempfile.TemporaryDirectory() as tmp:
            runner = ComponentBenchmarkRunner(results_dir=tmp, dry_run=False)
            rows = asyncio.run(
                runner._run_prompt_case(config, pipeline, prompt_def, 1, "text")
            )

    assert len(rows) == 1
    assert rows[0].status == "error"
    assert "503" in (rows[0].error or "")
    mock_client.post.assert_awaited_once()


def test_run_prompt_case_multi_turn_carries_conversation_id() -> None:
    """conversation_id from turn 0 must be sent on turn 1."""
    import unittest.mock as mock

    import httpx

    captured_payloads: list[dict] = []

    async def fake_post(url: str, **kwargs) -> httpx.Response:
        payload = kwargs.get("json", {})
        captured_payloads.append(
            {
                "conversation_id": payload.get("conversation_id"),
                "messages": [dict(m) for m in payload.get("messages", [])],
            }
        )
        resp = mock.MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "conversation_id": "conv-multi",
            "reply": {"content": f"reply-{len(captured_payloads)}"},
            "status": "success",
            "latency_ms": {"llm_call": 50.0, "total": 50.0},
        }
        return resp

    config = _minimal_config()
    pipeline = config.configs[0]
    prompt_def = {
        "id": "long_no_tool_01",
        "category": "long_no_tool",
        "turns": ["First question", "Follow-up question"],
        "expects_tool": False,
        "expected_tool_type": None,
        "expected_status": "success",
        "intent_name": "general_inquiry",
        "agent_template": "general_inquiry",
    }

    with mock.patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = mock.AsyncMock()
        mock_client.post = fake_post
        mock_client_cls.return_value.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        with tempfile.TemporaryDirectory() as tmp:
            runner = ComponentBenchmarkRunner(results_dir=tmp, dry_run=False)
            rows = asyncio.run(
                runner._run_prompt_case(config, pipeline, prompt_def, 1, "text")
            )

    assert len(rows) == 2
    assert captured_payloads[0]["conversation_id"] is None
    assert captured_payloads[1]["conversation_id"] == "conv-multi"
    assert len(captured_payloads[1]["messages"]) == 3
