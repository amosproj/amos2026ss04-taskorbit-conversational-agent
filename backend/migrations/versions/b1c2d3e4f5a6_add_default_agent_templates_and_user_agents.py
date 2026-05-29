"""add default_agent_templates and user_agents tables

Revision ID: b1c2d3e4f5a6
Revises: a0bc296ebba8
Create Date: 2026-05-29 22:00:00.000000

Creates two tables:
  - default_agent_templates: canonical seed agents (global, not user-owned)
  - user_agents: per-user agent instances cloned from templates on registration

Seed data: 4 standard agents that every new user receives automatically.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "a0bc296ebba8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---------------------------------------------------------------------------
# Default agent seed data
# Each config matches the AgentConfig shape: id, name, persona, greeting,
# stt, llm, tts, tools, persona_constraints.
# ---------------------------------------------------------------------------

_DEFAULT_STT = {"provider": "deepgram", "language": "en-US", "model": "nova-3"}
_DEFAULT_LLM = {"provider": "openai", "model": "gpt-4o-mini"}
_DEFAULT_TTS = {
    "provider": "elevenlabs",
    "voice_id": "21m00Tcm4TlvDq8ikWAM",
    "model": "eleven_multilingual_v2",
}

_SEED_TEMPLATES = [
    {
        "id": "sales-agent",
        "name": "Sales Agent",
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
        "is_active": True,
    },
    {
        "id": "technical-support-agent",
        "name": "Technical Support Agent",
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
        "is_active": True,
    },
    {
        "id": "general-inquiry-agent",
        "name": "General Inquiry Agent",
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
        "is_active": True,
    },
    {
        "id": "appointment-management-agent",
        "name": "Appointment Management Agent",
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
        "is_active": True,
    },
]


def upgrade() -> None:
    """Create default_agent_templates and user_agents tables and seed templates."""
    op.create_table(
        "default_agent_templates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_default_agent_templates_name"),
        "default_agent_templates",
        ["name"],
        unique=False,
    )

    op.create_table(
        "user_agents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["template_id"], ["default_agent_templates.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_agents_user_id", "user_agents", ["user_id"], unique=False)

    # Seed default templates — ON CONFLICT DO NOTHING makes this idempotent.
    templates_table = sa.table(
        "default_agent_templates",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("config", sa.JSON),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        templates_table,
        [
            {
                "id": t["id"],
                "name": t["name"],
                "config": t["config"],
                "is_active": t["is_active"],
            }
            for t in _SEED_TEMPLATES
        ],
    )


def downgrade() -> None:
    """Drop user_agents and default_agent_templates tables."""
    op.drop_index("ix_user_agents_user_id", table_name="user_agents")
    op.drop_table("user_agents")
    op.drop_index(op.f("ix_default_agent_templates_name"), table_name="default_agent_templates")
    op.drop_table("default_agent_templates")
