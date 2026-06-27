"""STT and TTS stage measurement for voice-path component benchmarks (#68).

Calls provider APIs directly so both ElevenLabs and Deepgram TTS configs can
be measured without routing through the LiveKit worker. STT uses a fixed
reference audio URL so latency is comparable across runs (transcript accuracy
is not evaluated here).
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

# Short public sample used for consistent STT latency measurement.
_STT_REFERENCE_AUDIO_URL = (
    "https://static.deepgram.com/examples/Bueller-Life-moves-pretty-fast.wav"
)


async def measure_stt_latency_ms(
    *,
    provider: str,
    model: str,
    api_key: str | None,
    timeout: float,
) -> float | None:
    """Return STT wall time in ms, or None when provider/key is unavailable."""
    if provider != "deepgram" or not api_key:
        return None

    url = "https://api.deepgram.com/v1/listen"
    params = {"model": model, "smart_format": "true"}
    payload = {"url": _STT_REFERENCE_AUDIO_URL}

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            url,
            params=params,
            json=payload,
            headers={
                "Authorization": f"Token {api_key}",
                "Content-Type": "application/json",
            },
        )
    if response.status_code != 200:
        return None
    return (time.perf_counter() - t0) * 1000


async def measure_tts_latency_ms(
    *,
    provider: str,
    voice_id: str,
    model: str,
    text: str,
    elevenlabs_api_key: str | None,
    deepgram_api_key: str | None,
    timeout: float,
) -> float | None:
    """Return TTS wall time in ms for the given provider."""
    trimmed = text.strip()
    if not trimmed:
        return None

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider == "elevenlabs":
            if not elevenlabs_api_key:
                return None
            response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": elevenlabs_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": trimmed[:5000],
                    "model_id": model,
                    "voice_settings": {
                        "stability": 0.75,
                        "similarity_boost": 0.75,
                    },
                },
            )
        elif provider == "deepgram":
            if not deepgram_api_key:
                return None
            tts_model = model or voice_id
            response = await client.post(
                "https://api.deepgram.com/v1/speak",
                params={"model": tts_model},
                headers={
                    "Authorization": f"Token {deepgram_api_key}",
                    "Content-Type": "application/json",
                },
                json={"text": trimmed[:5000]},
            )
        else:
            return None

    if response.status_code != 200:
        return None
    return (time.perf_counter() - t0) * 1000


def voice_api_keys() -> dict[str, str | None]:
    """Read provider API keys from the environment."""
    return {
        "deepgram": os.environ.get("DEEPGRAM_API_KEY"),
        "elevenlabs": os.environ.get("ELEVENLABS_API_KEY"),
    }


def merge_voice_latency(
    base: dict[str, Any],
    *,
    stt_ms: float | None,
    tts_ms: float | None,
) -> dict[str, Any]:
    """Combine conversation latency with measured STT/TTS stages for voice rows."""
    merged = dict(base)
    llm = merged.get("llm_call")
    tool = merged.get("tool_call") or 0.0
    llm_val = float(llm) if llm is not None else 0.0
    tool_val = float(tool) if tool is not None else 0.0
    stt_val = float(stt_ms) if stt_ms is not None else 0.0
    tts_val = float(tts_ms) if tts_ms is not None else 0.0

    if stt_ms is not None:
        merged["stt_processing"] = round(stt_ms, 1)
    if tts_ms is not None:
        merged["tts_synthesis"] = round(tts_ms, 1)

    stage_sum = stt_val + llm_val + tool_val + tts_val
    if stage_sum > 0:
        merged["voice_turn"] = round(stage_sum, 1)
        merged["total"] = round(stage_sum, 1)

    return merged
