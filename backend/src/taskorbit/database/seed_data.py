"""Default agent template seed data.

This module is the single source of truth for default agent configurations.
It is imported by:
  - The Alembic migration (b1c2d3e4f5a6) for the initial bulk insert
  - Tests that need realistic agent configs without hitting the DB
  - Any future management command that reloads/resets seed data

To add or update a template: edit this file and write a new data migration
that calls op.bulk_insert / op.execute UPDATE — do NOT edit the original
migration, which is immutable once merged.
"""

from __future__ import annotations

_DEFAULT_STT: dict = {"provider": "deepgram", "language": "en-US", "model": "nova-3"}
_DEFAULT_LLM: dict = {"provider": "openai", "model": "gpt-4o-mini"}
_DEFAULT_TTS: dict = {
    "provider": "elevenlabs",
    "voice_id": "21m00Tcm4TlvDq8ikWAM",
    "model": "eleven_multilingual_v2",
}


DEFAULT_AGENT_TEMPLATES: list[dict] = [
    {
        "id": "sales-agent",
        "name": "Sales Agent",
        "is_active": True,
        "config": {
            "id": "sales-agent",
            "name": "Sales Agent",
            "persona": (
                "A friendly and professional sales agent. "
                "You qualify leads, gather customer needs, and guide prospects "
                "through the buying process."
            ),
            "greeting": (
                "Hi! I'm your Sales Agent. I'm here to help you find the right "
                "solution for your needs. What can I help you with today?"
            ),
            "stt": _DEFAULT_STT,
            "llm": _DEFAULT_LLM,
            "tts": _DEFAULT_TTS,
            "tools": [],
            "persona_constraints": None,
        },
    },
    {
        "id": "technical-support-agent",
        "name": "Technical Support Agent",
        "is_active": True,
        "config": {
            "id": "technical-support-agent",
            "name": "Technical Support Agent",
            "persona": (
                "A knowledgeable technical support specialist. "
                "You diagnose issues, walk customers through troubleshooting steps, "
                "and escalate when needed."
            ),
            "greeting": (
                "Hello! I'm your Technical Support Agent. "
                "Tell me what issue you're experiencing and I'll help you resolve it."
            ),
            "stt": _DEFAULT_STT,
            "llm": _DEFAULT_LLM,
            "tts": _DEFAULT_TTS,
            "tools": [],
            "persona_constraints": None,
        },
    },
    {
        "id": "general-inquiry-agent",
        "name": "General Inquiry Agent",
        "is_active": True,
        "config": {
            "id": "general-inquiry-agent",
            "name": "General Inquiry Agent",
            "persona": (
                "A helpful general-purpose assistant. "
                "You answer frequently asked questions, provide product information, "
                "and direct customers to the right resource."
            ),
            "greeting": (
                "Hi there! I'm here to answer any questions you have. "
                "What would you like to know?"
            ),
            "stt": _DEFAULT_STT,
            "llm": _DEFAULT_LLM,
            "tts": _DEFAULT_TTS,
            "tools": [],
            "persona_constraints": None,
        },
    },
    {
        "id": "appointment-management-agent",
        "name": "Appointment Management Agent",
        "is_active": True,
        "config": {
            "id": "appointment-management-agent",
            "name": "Appointment Management Agent",
            "persona": (
                "A professional scheduling assistant. "
                "You help customers book, reschedule, and cancel appointments efficiently."
            ),
            "greeting": (
                "Hello! I'm your Appointment Agent. "
                "I can help you schedule, reschedule, or cancel an appointment. "
                "How can I assist you today?"
            ),
            "stt": _DEFAULT_STT,
            "llm": _DEFAULT_LLM,
            "tts": _DEFAULT_TTS,
            "tools": [],
            "persona_constraints": None,
        },
    },
]
