"""merge user_agents into agent_configurations

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-05-30 01:00:00.000000

Adds user_id, template_id, is_default, is_customized columns to
agent_configurations so it covers both admin configs and per-user copies.
Drops the now-redundant user_agents table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add new columns to agent_configurations
    op.add_column(
        "agent_configurations",
        sa.Column("user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "agent_configurations",
        sa.Column("template_id", sa.String(), nullable=True),
    )
    op.add_column(
        "agent_configurations",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "agent_configurations",
        sa.Column(
            "is_customized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 2. Add FK constraints and index
    op.create_foreign_key(
        "fk_agent_configurations_user_id",
        "agent_configurations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_agent_configurations_template_id",
        "agent_configurations",
        "default_agent_templates",
        ["template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_configurations_user_id",
        "agent_configurations",
        ["user_id"],
        unique=False,
    )

    # 3. Migrate existing user_agents rows into agent_configurations
    op.execute("""
        INSERT INTO agent_configurations (
            id, name, config, user_id, template_id, is_default, is_customized,
            created_at, updated_at
        )
        SELECT
            id, name, config, user_id, template_id, is_default, true,
            created_at, updated_at
        FROM user_agents
        ON CONFLICT (id) DO NOTHING
    """)

    # 4. Drop user_agents
    op.drop_index("ix_user_agents_user_id", table_name="user_agents")
    op.drop_table("user_agents")


def downgrade() -> None:
    # Recreate user_agents
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

    # Remove added columns from agent_configurations
    op.drop_index("ix_agent_configurations_user_id", table_name="agent_configurations")
    op.drop_constraint(
        "fk_agent_configurations_template_id", "agent_configurations", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_agent_configurations_user_id", "agent_configurations", type_="foreignkey"
    )
    op.drop_column("agent_configurations", "is_customized")
    op.drop_column("agent_configurations", "is_default")
    op.drop_column("agent_configurations", "template_id")
    op.drop_column("agent_configurations", "user_id")
