"""Component benchmark experiment configuration (#68)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class OllamaWarmupSettings:
    """Pre-benchmark Ollama VRAM primer + settle buffer (#68)."""

    enabled: bool = True
    buffer_seconds: float = 30.0
    timeout_seconds: float = 300.0

    @classmethod
    def from_yaml(cls, data: dict[str, Any] | None) -> OllamaWarmupSettings:
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", True)),
            buffer_seconds=float(data.get("buffer_seconds", 30.0)),
            timeout_seconds=float(data.get("timeout_seconds", 300.0)),
        )


@dataclass
class PipelineComponentConfig:
    """One STT + LLM + TTS combination to benchmark."""

    name: str
    stt_provider: str
    stt_model: str
    llm_provider: str
    llm_model: str
    tts_provider: str
    tts_voice_id: str
    tts_model: str

    def to_pipeline_dict(self) -> dict[str, str]:
        return {
            "stt_provider": self.stt_provider,
            "stt_model": self.stt_model,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "tts_provider": self.tts_provider,
            "tts_voice_id": self.tts_voice_id,
            "tts_model": self.tts_model,
        }


@dataclass
class ComponentBenchmarkConfig:
    """Top-level component benchmark experiment definition."""

    name: str
    description: str
    prompt_set: str
    repetitions: int
    concurrency: int
    timeout_seconds: int
    configs: list[PipelineComponentConfig]
    paths: list[str]
    tags: dict[str, str] | None = None
    ollama_warmup: OllamaWarmupSettings | None = None

    @classmethod
    def from_yaml(cls, path: Path | str) -> ComponentBenchmarkConfig:
        path = Path(path)
        with open(path) as handle:
            data = yaml.safe_load(handle)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid component benchmark config: {path}")

        required = {"name", "prompt_set", "configs"}
        missing = required - set(data.keys())
        if missing:
            raise ValueError(f"Missing required fields in {path}: {missing}")

        configs: list[PipelineComponentConfig] = []
        for entry in data["configs"]:
            configs.append(
                PipelineComponentConfig(
                    name=entry["name"],
                    stt_provider=entry["stt_provider"],
                    stt_model=entry["stt_model"],
                    llm_provider=entry["llm_provider"],
                    llm_model=entry["llm_model"],
                    tts_provider=entry["tts_provider"],
                    tts_voice_id=entry["tts_voice_id"],
                    tts_model=entry["tts_model"],
                )
            )

        raw_paths = data.get("paths", ["text"])
        if isinstance(raw_paths, str):
            raw_paths = [p.strip() for p in raw_paths.split(",") if p.strip()]
        paths = [str(p) for p in raw_paths]

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            prompt_set=data["prompt_set"],
            repetitions=data.get("repetitions", 3),
            concurrency=data.get("concurrency", 1),
            timeout_seconds=data.get("timeout_seconds", 120),
            configs=configs,
            paths=paths,
            tags=data.get("tags"),
            ollama_warmup=OllamaWarmupSettings.from_yaml(data.get("ollama_warmup")),
        )

    def validate(self) -> tuple[bool, str]:
        if self.repetitions < 1:
            return False, "repetitions must be >= 1"
        if self.concurrency < 1:
            return False, "concurrency must be >= 1"
        if self.timeout_seconds < 1:
            return False, "timeout_seconds must be >= 1"
        if len(self.configs) < 2:
            return False, "configs must include at least two pipeline combinations"
        valid_paths = {"text", "voice"}
        if not self.paths:
            return False, "paths must include at least one of: text, voice"
        invalid = set(self.paths) - valid_paths
        if invalid:
            return False, f"unsupported paths: {sorted(invalid)}"
        return True, ""
