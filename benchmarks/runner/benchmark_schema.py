"""Structured benchmark result schema — harness writes, aggregator reads (#68)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class BenchmarkConfigRow:
    stt_provider: str
    stt_model: str
    llm_provider: str
    llm_model: str
    tts_provider: str
    tts_voice_id: str
    tts_model: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkPromptRow:
    category: str
    id: str
    text: str
    expects_tool: bool
    expected_tool_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkLatencyMs:
    stt_processing: float | None = None
    llm_call: float | None = None
    llm_api: float | None = None
    tool_call: float | None = None
    tts_synthesis: float | None = None
    total: float | None = None
    voice_turn: float | None = None
    cumulative_total: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolReliabilityRow:
    tool_was_invoked: bool
    invoked_tool_type: str | None = None
    correct_tool_selected: bool | None = None
    result_incorporated_in_reply: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkResultRow:
    """One JSONL row per (config × prompt × run × turn)."""

    run_id: str
    timestamp: str
    run_number: int
    config: BenchmarkConfigRow
    prompt: BenchmarkPromptRow
    path: str
    latency_ms: BenchmarkLatencyMs
    tool_reliability: ToolReliabilityRow
    status: str
    error: str | None = None
    turn_index: int = 0
    turn_count: int = 1
    config_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "run_number": self.run_number,
            "config": self.config.to_dict(),
            "config_label": self.config_label,
            "prompt": self.prompt.to_dict(),
            "path": self.path,
            "turn_index": self.turn_index,
            "turn_count": self.turn_count,
            "latency_ms": self.latency_ms.to_dict(),
            "tool_reliability": self.tool_reliability.to_dict(),
            "status": self.status,
            "error": self.error,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def evaluate_tool_reliability(
    response: dict[str, Any],
    *,
    expects_tool: bool,
    expected_tool_type: str | None,
) -> ToolReliabilityRow:
    """Populate tool reliability fields from a ConversationResponse JSON body."""
    tool_invoked = response.get("tool_invoked")
    tool_was_invoked = tool_invoked is not None
    invoked_type = tool_invoked.get("type") if isinstance(tool_invoked, dict) else None

    if expects_tool:
        correct_tool_selected = (
            tool_was_invoked and invoked_type == expected_tool_type
            if expected_tool_type
            else tool_was_invoked
        )
    else:
        correct_tool_selected = not tool_was_invoked

    result_incorporated: bool | None = None
    if expects_tool and tool_was_invoked and invoked_type == "data_extraction":
        reply_text = (response.get("reply") or {}).get("content", "").lower()
        slots = response.get("extracted_slots") or {}
        values = [str(v).lower() for v in slots.values() if v]
        result_incorporated = any(value in reply_text for value in values) if values else False

    return ToolReliabilityRow(
        tool_was_invoked=tool_was_invoked,
        invoked_tool_type=invoked_type,
        correct_tool_selected=correct_tool_selected,
        result_incorporated_in_reply=result_incorporated,
    )


def latency_from_response(response: dict[str, Any], *, cumulative_ms: float | None = None) -> BenchmarkLatencyMs:
    """Map ConversationResponse.latency_ms into the benchmark schema."""
    raw = response.get("latency_ms") or {}
    return BenchmarkLatencyMs(
        stt_processing=raw.get("stt_processing"),
        llm_call=raw.get("llm_call"),
        llm_api=raw.get("llm_api"),
        tool_call=raw.get("tool_call"),
        tts_synthesis=raw.get("tts_synthesis"),
        total=raw.get("total"),
        voice_turn=raw.get("voice_turn"),
        cumulative_total=cumulative_ms,
    )
