"""Main benchmark runner — executes experiments and collects metrics."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from config import ExperimentConfig
from storage import ResultWriter, RunMetadata, TrialMetrics

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

        trials = []
        for trial_idx in range(config.repetitions):
            logger.info(f"Running trial {trial_idx + 1}/{config.repetitions}")
            metrics = await self._execute_trial(config, trial_idx, input_data)
            trials.append((trial_idx, metrics))

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
        """
        Execute a single trial with the given configuration.

        Placeholder: Will be extended to invoke agent/LLM with metrics collection.
        """
        try:
            start_time = time.time()

            await asyncio.sleep(0.1)

            elapsed_ms = (time.time() - start_time) * 1000

            metrics = TrialMetrics(
                latency_ms=elapsed_ms,
                component_latencies={},
                token_usage={"prompt": 0, "completion": 0},
                success=True,
                throughput=1.0 / (elapsed_ms / 1000),
            )
            return metrics

        except Exception as e:
            logger.error(f"Trial {trial_idx} failed: {e}")
            return TrialMetrics(
                latency_ms=0.0,
                success=False,
                error_message=str(e),
            )

    async def _dry_run_mock_results(self, config: ExperimentConfig) -> tuple[str, Path, dict]:
        """Generate mock results for dry-run mode."""
        trials = []
        for i in range(min(2, config.repetitions)):
            metrics = TrialMetrics(
                latency_ms=100.0 + (i * 10),
                component_latencies={"stt": 10.0, "llm": 50.0, "tts": 40.0},
                token_usage={"prompt": 50, "completion": 25},
                success=True,
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

    def _compute_summary(self, trials: list[tuple[int, TrialMetrics]]) -> dict[str, Any]:
        """Compute summary statistics for trials."""
        if not trials:
            return {}

        latencies = [m.latency_ms for _, m in trials]
        successes = sum(1 for _, m in trials if m.success)
        failures = len(trials) - successes

        summary = {
            "total_trials": len(trials),
            "successes": successes,
            "failures": failures,
            "success_rate": successes / len(trials),
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
            "min_latency_ms": min(latencies) if latencies else 0.0,
            "max_latency_ms": max(latencies) if latencies else 0.0,
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
