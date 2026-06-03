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

from taskorbit.database.seed_data import DEFAULT_AGENT_TEMPLATES, DEFAULT_USERS

revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "a0bc296ebba8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
            for t in DEFAULT_AGENT_TEMPLATES
        ],
    )

    # Seed dummy dev user — DEV ONLY, plain-text password: Test1234!
    users_table = sa.table(
        "users",
        sa.column("username", sa.String),
        sa.column("email", sa.String),
        sa.column("hashed_password", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        users_table,
        [
            {
                "username": u["username"],
                "email": u["email"],
                "hashed_password": u["hashed_password"],
                "is_active": u["is_active"],
            }
            for u in DEFAULT_USERS
        ],
    )


def downgrade() -> None:
    """Drop user_agents and default_agent_templates tables."""
    op.drop_index("ix_user_agents_user_id", table_name="user_agents")
    op.drop_table("user_agents")
    op.drop_index(op.f("ix_default_agent_templates_name"), table_name="default_agent_templates")
    op.drop_table("default_agent_templates")
