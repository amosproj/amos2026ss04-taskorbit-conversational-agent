"""Helpers to parse stored agent configuration blobs into orchestrator AgentConfig."""

from __future__ import annotations

from typing import Any

from taskorbit.types import AgentConfig


def logical_id_from_stored_blob(blob: dict[str, Any]) -> str:
    """Return the workflow/logical agent id from a saved FE or BE config blob."""
    return str(blob.get("agent_id") or blob.get("id") or "")


def agent_config_from_stored_blob(blob: dict[str, Any]) -> AgentConfig:
    """Map a saved agent-config JSON blob (FE or BE shape) to AgentConfig."""
    first_message = blob.get("first_message")
    greeting = blob.get("greeting") or ""
    if not greeting and isinstance(first_message, dict):
        greeting = str(first_message.get("message") or "")

    payload: dict[str, Any] = {
        "id": logical_id_from_stored_blob(blob),
        "name": blob.get("name") or "",
        "persona": blob.get("persona") or blob.get("instructions") or "",
        "greeting": greeting,
        "workflow_dependencies": blob.get("workflow_dependencies") or [],
        "allowed_handoffs": blob.get("allowed_handoffs") or [],
    }

    for key in ("stt", "llm", "tts", "tools", "persona_constraints", "context_limit"):
        if blob.get(key) is not None:
            payload[key] = blob[key]

    return AgentConfig.model_validate(payload)
