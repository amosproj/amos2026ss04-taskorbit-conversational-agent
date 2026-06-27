"""Tests for voice stage latency helpers — issue #68."""

from __future__ import annotations

import sys
from pathlib import Path

_RUNNER_DIR = Path(__file__).parent
if str(_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNNER_DIR))

from voice_stages import merge_voice_latency  # noqa: E402


def test_merge_voice_latency_sums_stages() -> None:
    merged = merge_voice_latency(
        {"llm_call": 120.0, "tool_call": 10.0, "total": 130.0},
        stt_ms=80.0,
        tts_ms=200.0,
    )
    assert merged["stt_processing"] == 80.0
    assert merged["tts_synthesis"] == 200.0
    assert merged["voice_turn"] == 410.0
    assert merged["total"] == 410.0


def test_merge_voice_latency_handles_missing_stt() -> None:
    merged = merge_voice_latency(
        {"llm_call": 100.0, "total": 100.0},
        stt_ms=None,
        tts_ms=50.0,
    )
    assert "stt_processing" not in merged or merged.get("stt_processing") is None
    assert merged["tts_synthesis"] == 50.0
    assert merged["total"] == 150.0
