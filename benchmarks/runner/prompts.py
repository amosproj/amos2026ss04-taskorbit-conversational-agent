"""Benchmark prompt set and AgentConfig builders for component benchmarking (#68)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_APPOINTMENT_EXTRACTION_PARAMS: list[dict[str, Any]] = [
    {
        "variable_name": "caller_name",
        "description": "Caller's full name.",
        "type": "string",
        "required": True,
    },
    {
        "variable_name": "email_address",
        "description": "Email address for confirmation.",
        "type": "email",
        "required": True,
    },
    {
        "variable_name": "phone_number",
        "description": "Callback phone number.",
        "type": "phone",
        "required": True,
    },
    {
        "variable_name": "preferred_date",
        "description": "Preferred appointment date.",
        "type": "date",
        "required": True,
    },
]

_BASE_PERSONA = (
    "You are a professional customer service agent for Mueller Plumbing. "
    "Be concise and helpful."
)


def load_prompt_set(path: Path | str) -> list[dict[str, Any]]:
    """Load the JSON prompt definitions used by the component benchmark harness."""
    prompt_path = Path(path)
    candidates = [prompt_path]
    if not prompt_path.is_absolute():
        bench_root = Path(__file__).resolve().parent.parent
        repo_root = bench_root.parent
        candidates.extend(
            [
                bench_root / prompt_path.name,
                repo_root / prompt_path,
                bench_root / prompt_path,
            ]
        )
        if prompt_path.parts and prompt_path.parts[0] == "benchmarks":
            candidates.append(repo_root / prompt_path)
            candidates.append(bench_root / Path(*prompt_path.parts[1:]))

    resolved: Path | None = None
    for candidate in candidates:
        if candidate.exists():
            resolved = candidate
            break
    if resolved is None:
        raise FileNotFoundError(f"Prompt set not found: {prompt_path}")
    with open(resolved) as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"Prompt set must be a JSON array: {resolved}")
    return data


def build_agent_config(
    template: str,
    pipeline: dict[str, Any],
) -> dict[str, Any]:
    """Build a wire-format AgentConfig dict for a benchmark prompt template."""
    stt = {
        "provider": pipeline["stt_provider"],
        "model": pipeline["stt_model"],
        "language": pipeline.get("stt_language", "multi"),
    }
    llm = {
        "provider": pipeline["llm_provider"],
        "model": pipeline["llm_model"],
    }
    tts = {
        "provider": pipeline["tts_provider"],
        "voice_id": pipeline["tts_voice_id"],
        "model": pipeline["tts_model"],
    }

    if template == "general_inquiry":
        return {
            "id": "benchmark-general-inquiry",
            "name": "Benchmark General Inquiry",
            "persona": _BASE_PERSONA + " Answer general questions about hours and services.",
            "greeting": "Hello! How can I help you today?",
            "stt": stt,
            "llm": llm,
            "tts": tts,
            "tools": [],
        }

    if template == "technical_support":
        return {
            "id": "benchmark-technical-support",
            "name": "Benchmark Technical Support",
            "persona": _BASE_PERSONA + " Troubleshoot technical issues and collect caller details.",
            "greeting": "Hi, technical support here. What issue are you experiencing?",
            "stt": stt,
            "llm": llm,
            "tts": tts,
            "tools": [],
        }

    if template == "transfer_technical_support":
        return {
            "id": "benchmark-transfer-agent",
            "name": "Benchmark Transfer Agent",
            "persona": _BASE_PERSONA + " Transfer callers to the right specialist when asked.",
            "greeting": "Hello! How can I help?",
            "stt": stt,
            "llm": llm,
            "tts": tts,
            "tools": [
                {
                    "id": "transfer-tech",
                    "name": "transfer_to_technical_support",
                    "type": "agent_transfer",
                    "description": "Transfer the caller to technical support.",
                    "confirmation": {"required": False, "prompt": ""},
                    "parameters": {"targets": ["technical_support"]},
                }
            ],
        }

    if template == "end_call":
        return {
            "id": "benchmark-end-call-agent",
            "name": "Benchmark End Call Agent",
            "persona": _BASE_PERSONA + " End the call politely when the caller is finished.",
            "greeting": "Hello! How can I help?",
            "stt": stt,
            "llm": llm,
            "tts": tts,
            "tools": [
                {
                    "id": "end-call-tool",
                    "name": "end_call",
                    "type": "end_call",
                    "description": "Ends the active call session.",
                    "confirmation": {"required": False, "prompt": ""},
                    "parameters": {},
                }
            ],
        }

    if template == "appointment_booking":
        return {
            "id": "benchmark-sales-agent",
            "name": "Benchmark Sales Agent",
            "persona": _BASE_PERSONA + " Book plumbing service appointments.",
            "greeting": "Hi, I can help you book a service appointment.",
            "stt": stt,
            "llm": llm,
            "tts": tts,
            "tools": [
                {
                    "id": "extract-appointment-data",
                    "name": "extract_appointment_data",
                    "type": "data_extraction",
                    "description": "Extract appointment booking details from the conversation.",
                    "confirmation": {"required": False, "prompt": ""},
                    "parameters": {"params": _APPOINTMENT_EXTRACTION_PARAMS},
                }
            ],
        }

    raise ValueError(f"Unknown benchmark agent template: {template!r}")
