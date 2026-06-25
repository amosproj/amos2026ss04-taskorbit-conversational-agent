"""Component benchmark runner — drives STT/LLM/TTS combinations through #68 prompt set."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from benchmark_schema import (
    BenchmarkConfigRow,
    BenchmarkPromptRow,
    BenchmarkResultRow,
    evaluate_tool_reliability,
    latency_from_response,
    utc_now_iso,
)
from component_config import ComponentBenchmarkConfig, PipelineComponentConfig
from prompts import build_agent_config, load_prompt_set

logger = logging.getLogger(__name__)


class ComponentResultWriter:
    """Append BenchmarkResultRow objects to a timestamped JSONL session file."""

    def __init__(self, results_dir: Path | str = "benchmarks/results/component") -> None:
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        self.session_file = self.results_dir / f"{stamp}_component_benchmark.jsonl"

    def append(self, row: BenchmarkResultRow) -> Path:
        with open(self.session_file, "a") as handle:
            handle.write(json.dumps(row.to_dict()) + "\n")
        return self.session_file


class ComponentBenchmarkRunner:
    """Execute component benchmarks and emit Endri's JSONL schema."""

    def __init__(
        self,
        results_dir: Path | str = "benchmarks/results/component",
        dry_run: bool = False,
    ) -> None:
        self.writer = ComponentResultWriter(results_dir)
        self.dry_run = dry_run

    async def run_experiment(self, config: ComponentBenchmarkConfig) -> tuple[Path, dict[str, Any]]:
        is_valid, error_msg = config.validate()
        if not is_valid:
            raise ValueError(error_msg)

        prompts = load_prompt_set(config.prompt_set)
        summary = {
            "experiment": config.name,
            "total_rows": 0,
            "success_rows": 0,
            "failure_rows": 0,
            "results_file": str(self.writer.session_file),
        }

        if self.dry_run:
            for run_number in range(1, config.repetitions + 1):
                for pipeline in config.configs:
                    for prompt_def in prompts:
                        row = self._mock_row(config, pipeline, prompt_def, run_number)
                        self.writer.append(row)
                        summary["total_rows"] += 1
                        summary["success_rows"] += 1
            return self.writer.session_file, summary

        for run_number in range(1, config.repetitions + 1):
            for pipeline in config.configs:
                for prompt_def in prompts:
                    rows = await self._run_prompt_case(
                        config,
                        pipeline,
                        prompt_def,
                        run_number,
                    )
                    for row in rows:
                        self.writer.append(row)
                        summary["total_rows"] += 1
                        if row.status == "success" or row.status == "ended":
                            summary["success_rows"] += 1
                        else:
                            summary["failure_rows"] += 1

        return self.writer.session_file, summary

    async def _run_prompt_case(
        self,
        config: ComponentBenchmarkConfig,
        pipeline: PipelineComponentConfig,
        prompt_def: dict[str, Any],
        run_number: int,
    ) -> list[BenchmarkResultRow]:
        api_url = os.environ.get("BENCHMARK_API_URL", "http://localhost:8000").rstrip("/")
        api_token = os.environ.get("BENCHMARK_API_TOKEN", "")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        agent_config = build_agent_config(
            prompt_def["agent_template"],
            pipeline.to_pipeline_dict(),
        )
        turns: list[str] = prompt_def["turns"]
        messages: list[dict[str, str]] = []
        conversation_id: str | None = None
        current_intent_name: str | None = None
        active_tool_id: str | None = None
        completed_workflow_steps: list[str] = []

        rows: list[BenchmarkResultRow] = []
        cumulative_ms = 0.0
        run_id = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S')}_run{run_number}"

        async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
            for turn_index, turn_text in enumerate(turns):
                messages.append({"role": "user", "content": turn_text})
                payload: dict[str, Any] = {
                    "conversation_id": conversation_id,
                    "agent_config": agent_config,
                    "messages": messages,
                    "current_intent_name": current_intent_name,
                    "active_tool_id": active_tool_id,
                    "completed_workflow_steps": completed_workflow_steps,
                }

                try:
                    t_start = time.perf_counter()
                    response = await client.post(
                        f"{api_url}/v1/conversations/process",
                        json=payload,
                        headers=headers,
                    )
                    wall_ms = (time.perf_counter() - t_start) * 1000

                    if response.status_code != 200:
                        rows.append(
                            self._error_row(
                                config,
                                pipeline,
                                prompt_def,
                                run_number,
                                run_id,
                                turn_index,
                                len(turns),
                                turn_text,
                                f"HTTP {response.status_code}: {response.text[:300]}",
                            )
                        )
                        break

                    data: dict[str, Any] = response.json()
                    conversation_id = data.get("conversation_id", conversation_id)
                    current_intent_name = data.get("locked_intent_name")
                    active_tool_id = data.get("next_active_tool_id")
                    completed_workflow_steps = data.get("completed_workflow_steps", [])

                    turn_total = (data.get("latency_ms") or {}).get("total") or wall_ms
                    cumulative_ms += float(turn_total)

                    reliability = evaluate_tool_reliability(
                        data,
                        expects_tool=bool(prompt_def.get("expects_tool")),
                        expected_tool_type=prompt_def.get("expected_tool_type"),
                    )
                    latency = latency_from_response(data, cumulative_ms=cumulative_ms)

                    rows.append(
                        BenchmarkResultRow(
                            run_id=run_id,
                            timestamp=utc_now_iso(),
                            run_number=run_number,
                            config_label=pipeline.name,
                            config=BenchmarkConfigRow(
                                stt_provider=pipeline.stt_provider,
                                stt_model=pipeline.stt_model,
                                llm_provider=pipeline.llm_provider,
                                llm_model=pipeline.llm_model,
                                tts_provider=pipeline.tts_provider,
                                tts_voice_id=pipeline.tts_voice_id,
                                tts_model=pipeline.tts_model,
                            ),
                            prompt=BenchmarkPromptRow(
                                category=prompt_def["category"],
                                id=prompt_def["id"],
                                text=turn_text,
                                expects_tool=bool(prompt_def.get("expects_tool")),
                                expected_tool_type=prompt_def.get("expected_tool_type"),
                            ),
                            path="text",
                            turn_index=turn_index,
                            turn_count=len(turns),
                            latency_ms=latency,
                            tool_reliability=reliability,
                            status=str(data.get("status", "error")),
                            error=data.get("error") or None,
                        )
                    )

                    reply_content = (data.get("reply") or {}).get("content", "")
                    if reply_content:
                        messages.append({"role": "assistant", "content": reply_content})

                except httpx.TimeoutException:
                    rows.append(
                        self._error_row(
                            config,
                            pipeline,
                            prompt_def,
                            run_number,
                            run_id,
                            turn_index,
                            len(turns),
                            turn_text,
                            f"Request timed out after {config.timeout_seconds}s",
                        )
                    )
                    break
                except httpx.ConnectError as exc:
                    rows.append(
                        self._error_row(
                            config,
                            pipeline,
                            prompt_def,
                            run_number,
                            run_id,
                            turn_index,
                            len(turns),
                            turn_text,
                            f"Could not connect to {api_url}: {exc}",
                        )
                    )
                    break

        return rows

    def _error_row(
        self,
        config: ComponentBenchmarkConfig,
        pipeline: PipelineComponentConfig,
        prompt_def: dict[str, Any],
        run_number: int,
        run_id: str,
        turn_index: int,
        turn_count: int,
        turn_text: str,
        error: str,
    ) -> BenchmarkResultRow:
        return BenchmarkResultRow(
            run_id=run_id,
            timestamp=utc_now_iso(),
            run_number=run_number,
            config_label=pipeline.name,
            config=BenchmarkConfigRow(
                stt_provider=pipeline.stt_provider,
                stt_model=pipeline.stt_model,
                llm_provider=pipeline.llm_provider,
                llm_model=pipeline.llm_model,
                tts_provider=pipeline.tts_provider,
                tts_voice_id=pipeline.tts_voice_id,
                tts_model=pipeline.tts_model,
            ),
            prompt=BenchmarkPromptRow(
                category=prompt_def["category"],
                id=prompt_def["id"],
                text=turn_text,
                expects_tool=bool(prompt_def.get("expects_tool")),
                expected_tool_type=prompt_def.get("expected_tool_type"),
            ),
            path="text",
            turn_index=turn_index,
            turn_count=turn_count,
            latency_ms=latency_from_response({}),
            tool_reliability=evaluate_tool_reliability(
                {},
                expects_tool=bool(prompt_def.get("expects_tool")),
                expected_tool_type=prompt_def.get("expected_tool_type"),
            ),
            status="error",
            error=error,
        )

    def _mock_row(
        self,
        config: ComponentBenchmarkConfig,
        pipeline: PipelineComponentConfig,
        prompt_def: dict[str, Any],
        run_number: int,
    ) -> BenchmarkResultRow:
        turn_text = prompt_def["turns"][0]
        return BenchmarkResultRow(
            run_id=f"dry-run_run{run_number}",
            timestamp=utc_now_iso(),
            run_number=run_number,
            config_label=pipeline.name,
            config=BenchmarkConfigRow(
                stt_provider=pipeline.stt_provider,
                stt_model=pipeline.stt_model,
                llm_provider=pipeline.llm_provider,
                llm_model=pipeline.llm_model,
                tts_provider=pipeline.tts_provider,
                tts_voice_id=pipeline.tts_voice_id,
                tts_model=pipeline.tts_model,
            ),
            prompt=BenchmarkPromptRow(
                category=prompt_def["category"],
                id=prompt_def["id"],
                text=turn_text,
                expects_tool=bool(prompt_def.get("expects_tool")),
                expected_tool_type=prompt_def.get("expected_tool_type"),
            ),
            path="text",
            turn_index=0,
            turn_count=len(prompt_def["turns"]),
            latency_ms=latency_from_response(
                {"latency_ms": {"llm_call": 120.0, "total": 150.0, "tool_call": 5.0}}
            ),
            tool_reliability=evaluate_tool_reliability(
                {},
                expects_tool=bool(prompt_def.get("expects_tool")),
                expected_tool_type=prompt_def.get("expected_tool_type"),
            ),
            status="success",
            error=None,
        )
