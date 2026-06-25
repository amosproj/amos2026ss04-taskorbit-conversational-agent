"""Main benchmark runner — executes experiments and collects metrics."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from config import ExperimentConfig
from metrics import capture_component_latencies, capture_system_metrics
from storage import ResultWriter, RunMetadata, TrialMetrics

# Default prompt used when the input JSONL is missing or exhausted.
_DEFAULT_PROMPT = "What tasks do I have due today?"

# Maps config provider names to the value the backend LLMProvider enum expects.
# "local" is kept as an alias for openai for backwards-compat with older configs.
_PROVIDER_MAP: dict[str, str] = {
    "openai": "openai",
    "google": "google",
    "openrouter": "openrouter",
    "local": "openai",
}

# Minimal AgentConfig sent with every benchmark request.
# Persona is intentionally short so it doesn't inflate prompt token counts.
_BENCH_AGENT: dict[str, Any] = {
    "id": "benchmark-agent",
    "name": "Benchmark Agent",
    "persona": "You are a helpful task management assistant. Be concise.",
    "greeting": "Hello!",
}

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """Execute benchmark experiments and collect results."""

    def __init__(
        self,
        results_dir: Path | str = "benchmarks/results",
        dry_run: bool = False,
    ):
        """Initialize benchmark runner."""
        self.results_dir = Path(results_dir)
        self.writer = ResultWriter(results_dir)
        self.dry_run = dry_run
        logger.info(f"BenchmarkRunner initialized (dry_run={dry_run})")

    async def run_experiment(
        self,
        config: ExperimentConfig,
        input_data: list[dict[str, Any]] | None = None,
    ) -> tuple[str, Path, dict[str, Any]]:
        """
        Execute a single experiment and return results.

        Args:
            config: Experiment configuration
            input_data: Optional input data for trials

        Returns:
            (run_id, results_file_path, summary_stats)
        """
        is_valid, error_msg = config.validate()
        if not is_valid:
            logger.error(f"Invalid config: {error_msg}")
            raise ValueError(f"Invalid config: {error_msg}")

        logger.info(f"Starting experiment: {config.name}")
        if self.dry_run:
            logger.info("DRY RUN: Would execute the following trials")
            logger.info(f"  Repetitions: {config.repetitions}")
            logger.info(f"  Concurrency: {config.concurrency}")
            logger.info(f"  Metrics: {config.metrics}")
            # Return mock results for dry-run
            return await self._dry_run_mock_results(config)

        trials = await self._execute_trials(config, input_data)

        metadata = RunMetadata(
            run_id="",
            config_name=config.name,
            timestamp="",
            git_sha=self._get_git_sha(),
            docker_image=self._get_docker_image(),
        )

        run_id, results_file = self.writer.write_run(config.name, trials, metadata)

        summary = self._compute_summary(trials)
        logger.info(f"Experiment {config.name} completed: {summary}")

        return run_id, results_file, summary

    async def _execute_trial(
        self,
        config: ExperimentConfig,
        trial_idx: int,
        input_data: list[dict[str, Any]] | None = None,
    ) -> TrialMetrics:
        """Call the TaskOrbit /v1/conversations/process endpoint and record latency.

        Environment variables:
            BENCHMARK_API_URL   Base URL of the running backend (default: http://localhost:8000).
            BENCHMARK_API_TOKEN Bearer token for authentication. Obtain by logging in through
                                the frontend and copying the token from the browser's dev tools
                                (Application → Local Storage → token).
        """
        api_url = os.environ.get("BENCHMARK_API_URL", "http://localhost:8000").rstrip("/")
        api_token = os.environ.get("BENCHMARK_API_TOKEN", "")

        # Cycle through input prompts so each trial uses a different one.
        prompt = _DEFAULT_PROMPT
        if input_data:
            entry = input_data[trial_idx % len(input_data)]
            prompt = entry.get("input", _DEFAULT_PROMPT)

        backend_provider = _PROVIDER_MAP.get(config.provider, config.provider)

        payload: dict[str, Any] = {
            "agent_config": {
                **_BENCH_AGENT,
                "llm": {"provider": backend_provider, "model": config.model},
            },
            "messages": [{"role": "user", "content": prompt}],
        }

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        logger.debug(
            f"Trial {trial_idx}: POST {api_url}/v1/conversations/process "
            f"provider={backend_provider} model={config.model} prompt={prompt[:60]!r}"
        )

        try:
            t_start = time.perf_counter()

            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                response = await client.post(
                    f"{api_url}/v1/conversations/process",
                    json=payload,
                    headers=headers,
                )

            elapsed_ms = (time.perf_counter() - t_start) * 1000

            if response.status_code != 200:
                error_body = response.text[:300]
                logger.error(f"Trial {trial_idx} HTTP {response.status_code}: {error_body}")
                return self._build_trial_metrics(
                    latency_ms=elapsed_ms,
                    success=False,
                    error_message=f"HTTP {response.status_code}: {error_body}",
                )

            data: dict[str, Any] = response.json()
            reply_text: str = data.get("reply", {}).get("content", "")

            logger.debug(
                f"Trial {trial_idx} completed in {elapsed_ms:.1f}ms "
                f"reply_len={len(reply_text)}"
            )

            return self._build_trial_metrics(
                latency_ms=elapsed_ms,
                success=True,
                component_latencies=capture_component_latencies(),
                token_usage={"prompt": 0, "completion": 0},
            )

        except httpx.TimeoutException:
            logger.error(f"Trial {trial_idx} timed out after {config.timeout_seconds}s")
            return self._build_trial_metrics(
                latency_ms=config.timeout_seconds * 1000.0,
                success=False,
                error_message=f"Request timed out after {config.timeout_seconds}s",
            )
        except httpx.ConnectError as exc:
            logger.error(f"Trial {trial_idx} connection error: {exc}")
            return self._build_trial_metrics(
                latency_ms=0.0,
                success=False,
                error_message=f"Could not connect to {api_url} — is the backend running?",
            )
        except Exception as exc:
            logger.error(f"Trial {trial_idx} unexpected error: {exc}")
            return self._build_trial_metrics(
                latency_ms=0.0,
                success=False,
                error_message=str(exc),
            )

    async def _dry_run_mock_results(self, config: ExperimentConfig) -> tuple[str, Path, dict]:
        """Generate mock results for dry-run mode."""
        trials = []
        for i in range(config.repetitions):
            metrics = self._build_trial_metrics(
                latency_ms=100.0 + (i * 10),
                success=True,
                component_latencies={"stt": 10.0, "llm": 50.0, "tts": 40.0},
                token_usage={"prompt": 50, "completion": 25},
                throughput=10.0,
            )
            trials.append((i, metrics))

        metadata = RunMetadata(
            run_id="",
            config_name=config.name,
            timestamp="",
        )

        run_id, results_file = self.writer.write_run(config.name, trials, metadata)
        summary = self._compute_summary(trials)

        return run_id, results_file, summary

    async def _execute_trials(
        self,
        config: ExperimentConfig,
        input_data: list[dict[str, Any]] | None = None,
    ) -> list[tuple[int, TrialMetrics]]:
        """Execute benchmark trials with the configured concurrency limit."""
        semaphore = asyncio.Semaphore(config.concurrency)

        async def _run_trial(trial_idx: int) -> tuple[int, TrialMetrics]:
            async with semaphore:
                logger.info(f"Running trial {trial_idx + 1}/{config.repetitions}")
                metrics = await self._execute_trial(config, trial_idx, input_data)
                return trial_idx, metrics

        trials = await asyncio.gather(*(_run_trial(trial_idx) for trial_idx in range(config.repetitions)))
        return sorted(trials, key=lambda item: item[0])

    def _build_trial_metrics(
        self,
        latency_ms: float,
        *,
        success: bool,
        component_latencies: dict[str, float] | None = None,
        token_usage: dict[str, int] | None = None,
        error_message: str | None = None,
        throughput: float | None = None,
    ) -> TrialMetrics:
        """Create a TrialMetrics object with the standard benchmark shape."""
        return TrialMetrics(
            latency_ms=latency_ms,
            component_latencies=component_latencies or capture_component_latencies(),
            token_usage=token_usage or {"prompt": 0, "completion": 0},
            success=success,
            error_message=error_message,
            throughput=throughput if throughput is not None else (1000.0 / latency_ms if success and latency_ms > 0 else 0.0),
            system_metrics=capture_system_metrics(),
        )

    def _compute_summary(self, trials: list[tuple[int, TrialMetrics]]) -> dict[str, Any]:
        """Compute summary statistics for trials."""
        if not trials:
            return {}

        latencies = [m.latency_ms for _, m in trials]
        successes = sum(1 for _, m in trials if m.success)
        failures = len(trials) - successes
        throughputs = [m.throughput for _, m in trials if m.throughput > 0]

        summary = {
            "total_trials": len(trials),
            "successes": successes,
            "failures": failures,
            "failure_count": failures,
            "success_rate": successes / len(trials),
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
            "min_latency_ms": min(latencies) if latencies else 0.0,
            "max_latency_ms": max(latencies) if latencies else 0.0,
            "throughput_avg": sum(throughputs) / len(throughputs) if throughputs else 0.0,
        }

        all_tokens = {}
        for _, m in trials:
            for key, val in m.token_usage.items():
                all_tokens[key] = all_tokens.get(key, 0) + val
        if all_tokens:
            summary["total_tokens"] = all_tokens

        return summary

    def _get_git_sha(self) -> str:
        """Get current git commit SHA."""
        try:
            import subprocess

            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception as e:
            logger.warning(f"Could not get git SHA: {e}")
            return ""

    def _get_docker_image(self) -> str:
        """Get docker image info if running in container."""
        try:
            with open("/.dockerenv") as _:
                return "docker"
        except FileNotFoundError:
            return ""
