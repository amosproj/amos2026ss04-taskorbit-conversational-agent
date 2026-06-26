"""Default seed data: agent templates and a dummy dev user.

This module is the single source of truth for default seed data.
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


def _persona_constraints(*, scope: str, out_of_scope: list[str], refusal_template: str) -> dict:
    """Build a persona_constraints block — same shape on every agent, content per role."""
    return {
        "scope": scope,
        "out_of_scope": out_of_scope,
        "refusal_template": refusal_template,
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
            "confirmations": {"required": False, "tools": []},
            "persona_constraints": _persona_constraints(
                scope="TechStore sales: product recommendations, pricing, and guiding prospects to purchase.",
                out_of_scope=[
                    "medical advice",
                    "legal advice",
                    "financial advice",
                    "technical troubleshooting",
                    "recipes",
                    "cooking",
                ],
                refusal_template=(
                    "I'm your TechStore sales assistant — I can help with products and purchasing. "
                    "I can't assist with that topic. Would you like help choosing a product or placing an order?"
                ),
            ),
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
            "confirmations": {"required": False, "tools": []},
            "persona_constraints": _persona_constraints(
                scope="TechStore technical support: diagnosing product issues and troubleshooting steps.",
                out_of_scope=[
                    "medical advice",
                    "legal advice",
                    "financial advice",
                    "sales and pricing quotes",
                    "recipes",
                    "cooking",
                ],
                refusal_template=(
                    "I'm a TechStore technical support agent and can help with product issues. "
                    "I can't assist with that topic. What technical problem are you seeing?"
                ),
            ),
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
                "A helpful TechStore assistant for product FAQs, ordering, and directing "
                "customers to the right team. You do not answer general knowledge or off-store topics."
            ),
            "greeting": (
                "Hi! I can help with TechStore product info, orders, and store questions. "
                "What would you like to know?"
            ),
            "stt": _DEFAULT_STT,
            "llm": _DEFAULT_LLM,
            "tts": _DEFAULT_TTS,
            "tools": [],
            "confirmations": {"required": False, "tools": []},
            "persona_constraints": _persona_constraints(
                scope="TechStore product information, ordering, returns, and store FAQs.",
                out_of_scope=[
                    "recipes",
                    "cooking",
                    "medical advice",
                    "legal advice",
                    "financial advice",
                    "therapy or emotional counseling",
                    "NFTs",
                    "crypto",
                    "general technical tutorials",
                ],
                refusal_template=(
                    "I'm here to help with TechStore product and ordering questions. "
                    "I can't assist with that topic — is there something about our store I can help with?"
                ),
            ),
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
            "confirmations": {"required": False, "tools": []},
            "persona_constraints": _persona_constraints(
                scope="Booking, rescheduling, and cancelling TechStore service appointments.",
                out_of_scope=[
                    "medical advice",
                    "legal advice",
                    "financial advice",
                    "technical troubleshooting",
                    "product recommendations",
                    "recipes",
                    "cooking",
                ],
                refusal_template=(
                    "I help with appointment scheduling at TechStore. "
                    "I can't assist with that topic — would you like to book, reschedule, or cancel an appointment?"
                ),
            ),
        },
    },
    {
        "id": "customer-dissatisfaction-agent",
        "name": "Customer Dissatisfaction Agent",
        "is_active": True,
        "config": {
            "id": "customer-dissatisfaction-agent",
            "name": "Customer Dissatisfaction Agent",
            "persona": (
                "An empathetic customer service specialist focused on complaint resolution. "
                "You acknowledge issues, capture the details, and arrange the preferred resolution channel."
            ),
            "greeting": (
                "I'm sorry to hear you're having a frustrating experience. "
                "I'm here to help resolve this — could you tell me what happened?"
            ),
            "stt": _DEFAULT_STT,
            "llm": _DEFAULT_LLM,
            "tts": _DEFAULT_TTS,
            "tools": [],
            "confirmations": {"required": False, "tools": []},
            "persona_constraints": _persona_constraints(
                scope="TechStore complaint intake, resolution options, and escalation.",
                out_of_scope=[
                    "medical advice",
                    "legal advice",
                    "financial advice",
                    "technical troubleshooting",
                    "recipes",
                    "cooking",
                    "therapy or emotional counseling",
                ],
                refusal_template=(
                    "I'm here to help resolve your TechStore experience. "
                    "I can't provide professional advice on that topic — can you tell me more about the issue with your order or service?"
                ),
            ),
        },
    },
]

# ---------------------------------------------------------------------------
# Dummy dev user
# DEV ONLY — do not use in production.
# Plain-text password: Test1234!
# hashed_password is a SHA-256 placeholder. Replace with a proper bcrypt hash
# once a password hashing library (e.g. passlib[bcrypt]) is added as a dep.
# ---------------------------------------------------------------------------

DEFAULT_USERS: list[dict] = [
    {
        "username": "dev_user",
        "email": "dev@taskorbit.local",
        "hashed_password": "sha256:0fadf52a4580cfebb99e61162139af3d3a6403c1d36b83e4962b721d1c8cbd0b",
        "is_active": True,
    },
]
