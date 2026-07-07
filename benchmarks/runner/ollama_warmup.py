"""Ollama VRAM warmup before component benchmark timed runs (#68).

Self-hosted Ollama loads weights into GPU memory on first use. Without a primer
request the first benchmark turn includes that cold-start cost and skews latency.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from component_config import OllamaWarmupSettings, PipelineComponentConfig
from prompts import build_agent_config

logger = logging.getLogger(__name__)

_WARMUP_USER_MESSAGE = "Reply with one short word only."
_WARMUP_INTENT = "general_inquiry"


def effective_warmup_buffer_seconds(settings: OllamaWarmupSettings) -> float:
    """Env OLLAMA_WARMUP_BUFFER_SECONDS overrides YAML when set."""
    raw = os.environ.get("OLLAMA_WARMUP_BUFFER_SECONDS")
    if raw is None or raw.strip() == "":
        return settings.buffer_seconds
    return float(raw)


async def warmup_ollama_pipeline(
    *,
    api_url: str,
    pipeline: PipelineComponentConfig,
    headers: dict[str, str],
    settings: OllamaWarmupSettings,
) -> float | None:
    """Prime Ollama via the backend conversation API; wait buffer; return warmup ms.

    Returns elapsed milliseconds for the primer LLM call, or None when skipped.
  """
    if not settings.enabled or pipeline.llm_provider != "ollama":
        return None

    buffer_s = effective_warmup_buffer_seconds(settings)
    agent_config = build_agent_config("general_inquiry", pipeline.to_pipeline_dict())
    payload: dict[str, Any] = {
        "conversation_id": None,
        "agent_config": agent_config,
        "messages": [{"role": "user", "content": _WARMUP_USER_MESSAGE}],
        "current_intent_name": _WARMUP_INTENT,
        "selected_agent": None,
        "active_tool_id": None,
        "completed_workflow_steps": [],
    }

    logger.info(
        "Ollama warmup: loading %s into VRAM via %s (timeout=%ss)",
        pipeline.llm_model,
        api_url,
        settings.timeout_seconds,
    )

    t_start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
            response = await client.post(
                f"{api_url.rstrip('/')}/v1/conversations/process",
                json=payload,
                headers=headers,
            )
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        if response.status_code != 200:
            logger.warning(
                "Ollama warmup: primer request failed HTTP %s — %s",
                response.status_code,
                response.text[:200],
            )
        else:
            logger.info(
                "Ollama warmup: model responded in %.0f ms",
                elapsed_ms,
            )
    except httpx.HTTPError as exc:
        logger.warning("Ollama warmup: primer request error — %s", exc)
        elapsed_ms = (time.perf_counter() - t_start) * 1000

    if buffer_s > 0:
        logger.info(
            "Ollama warmup: waiting %.0fs buffer for VRAM to settle before timed runs",
            buffer_s,
        )
        await asyncio.sleep(buffer_s)

    return elapsed_ms
