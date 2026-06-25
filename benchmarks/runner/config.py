"""Benchmark experiment configuration schema and parser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ExperimentConfig:
    """Experiment configuration schema."""

    name: str
    description: str
    provider: str
    model: str
    input_set: str
    repetitions: int
    concurrency: int
    metrics: list[str]
    timeout_seconds: int = 300
    tags: dict[str, str] | None = None

    @classmethod
    def from_yaml(cls, path: Path | str) -> ExperimentConfig:
        """Load and validate experiment config from YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Invalid config format: expected dict, got {type(data)}")

        required_fields = {"name", "provider", "model", "input_set", "repetitions"}
        missing = required_fields - set(data.keys())
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            provider=data["provider"],
            model=data["model"],
            input_set=data["input_set"],
            repetitions=data.get("repetitions", 1),
            concurrency=data.get("concurrency", 1),
            metrics=data.get("metrics", ["latency_e2e", "token_usage", "errors"]),
            timeout_seconds=data.get("timeout_seconds", 300),
            tags=data.get("tags"),
        )

    def validate(self) -> tuple[bool, str]:
        """Validate configuration. Returns (is_valid, error_message)."""
        if self.repetitions < 1:
            return False, "repetitions must be >= 1"
        if self.concurrency < 1:
            return False, "concurrency must be >= 1"
        if self.timeout_seconds < 1:
            return False, "timeout_seconds must be >= 1"
        if not self.metrics:
            return False, "metrics list cannot be empty"

        valid_metrics = {
            "latency_e2e",
            "latency_components",
            "token_usage",
            "errors",
            "throughput",
        }
        invalid = set(self.metrics) - valid_metrics
        if invalid:
            return False, f"Invalid metrics: {invalid}. Valid: {valid_metrics}"

        return True, ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize config to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "provider": self.provider,
            "model": self.model,
            "input_set": self.input_set,
            "repetitions": self.repetitions,
            "concurrency": self.concurrency,
            "metrics": self.metrics,
            "timeout_seconds": self.timeout_seconds,
            "tags": self.tags,
        }
