"""Result storage and serialization for benchmark runs."""

from __future__ import annotations

import csv
import json
import logging
import platform
import uuid
from importlib import metadata as importlib_metadata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RUNTIME_DEPENDENCIES = ("httpx", "PyYAML", "psutil")


@dataclass
class TrialMetrics:
    """Metrics collected for a single trial."""

    latency_ms: float
    component_latencies: dict[str, float] = field(default_factory=dict)
    token_usage: dict[str, int] = field(default_factory=dict)
    success: bool = True
    error_message: str | None = None
    throughput: float = 0.0
    system_metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize metrics to dictionary."""
        return asdict(self)


@dataclass
class RunMetadata:
    """Metadata for a benchmark run."""

    run_id: str
    config_name: str
    timestamp: str
    git_sha: str = ""
    docker_image: str = ""
    python_version: str = ""
    dependencies: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize metadata to dictionary."""
        return asdict(self)


class ResultWriter:
    """Writes benchmark results to JSONL and maintains index.csv."""

    def __init__(self, results_dir: Path | str = "benchmarks/results"):
        """Initialize result writer."""
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.results_dir / "index.csv"
        self._ensure_index_exists()

    def _ensure_index_exists(self) -> None:
        """Create index.csv with headers if it doesn't exist."""
        if not self.index_file.exists():
            headers = [
                "run_id",
                "config_name",
                "timestamp",
                "avg_latency_ms",
                "min_latency_ms",
                "max_latency_ms",
                "success_rate",
                "total_trials",
                "throughput_avg",
                "path_to_results",
            ]
            with open(self.index_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
            logger.debug(f"Created index file: {self.index_file}")

    def write_run(
        self,
        config_name: str,
        trials: list[tuple[int, TrialMetrics]],
        metadata: RunMetadata | None = None,
    ) -> tuple[str, Path]:
        """
        Write a complete benchmark run to JSONL and update index.csv.

        Args:
            config_name: Name of the experiment configuration
            trials: List of (trial_index, metrics) tuples
            metadata: Optional run metadata (git sha, docker image, etc.)

        Returns:
            (run_id, results_file_path)
        """
        run_id = str(uuid.uuid4())[:8]
        timestamp = datetime.utcnow().isoformat()

        if metadata is None:
            metadata = RunMetadata(
                run_id=run_id,
                config_name=config_name,
                timestamp=timestamp,
            )

        if not metadata.run_id:
            metadata.run_id = run_id
        if not metadata.timestamp:
            metadata.timestamp = timestamp
        if not metadata.python_version:
            metadata.python_version = platform.python_version()
        if not metadata.dependencies:
            metadata.dependencies = _collect_dependency_versions()

        run_dir = self.results_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        results_file = run_dir / "results.jsonl"

        with open(results_file, "w") as f:
            for trial_index, metrics in trials:
                result = {
                    "run_id": run_id,
                    "timestamp": timestamp,
                    "trial_index": trial_index,
                    "metrics": metrics.to_dict(),
                    "environment": metadata.to_dict(),
                }
                f.write(json.dumps(result) + "\n")

        logger.info(f"Wrote {len(trials)} trials to {results_file}")

        latencies = [m.latency_ms for _, m in trials]
        successes = sum(1 for _, m in trials if m.success)
        throughputs = [m.throughput for _, m in trials if m.throughput > 0]

        index_row = {
            "run_id": run_id,
            "config_name": config_name,
            "timestamp": timestamp,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
            "min_latency_ms": min(latencies) if latencies else 0.0,
            "max_latency_ms": max(latencies) if latencies else 0.0,
            "success_rate": successes / len(trials) if trials else 0.0,
            "total_trials": len(trials),
            "throughput_avg": sum(throughputs) / len(throughputs)
            if throughputs
            else 0.0,
            "path_to_results": str(results_file),
        }

        with open(self.index_file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=index_row.keys())
            writer.writerow(index_row)

        logger.info(f"Updated index: {self.index_file}")

        return run_id, results_file

    def load_run(self, run_id: str) -> list[dict[str, Any]]:
        """Load all trials from a run by run_id."""
        results_file = self.results_dir / run_id / "results.jsonl"
        if not results_file.exists():
            raise FileNotFoundError(f"Results file not found: {results_file}")

        trials = []
        with open(results_file) as f:
            for line in f:
                if line.strip():
                    trials.append(json.loads(line))
        return trials

    def load_index(self) -> list[dict[str, Any]]:
        """Load the results index."""
        if not self.index_file.exists():
            return []

        results = []
        with open(self.index_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                results.append(row)
        return results


def _collect_dependency_versions() -> dict[str, str]:
    """Return versions of the benchmark runtime dependencies."""
    versions: dict[str, str] = {}
    for dist_name in _RUNTIME_DEPENDENCIES:
        try:
            versions[dist_name] = importlib_metadata.version(dist_name)
        except importlib_metadata.PackageNotFoundError:
            continue
    return versions
