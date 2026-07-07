"""dedupe slot_extractions and add unique constraint

Revision ID: a1b2c3d4e5f6
Revises: e5f6a7b8c9d0
Create Date: 2026-07-07

Removes duplicate (conversation_id, tool_id, field_name) rows created before the
write-side upsert was introduced, keeping the highest-id row for each key.  Then
adds a unique constraint so the application-level INSERT … ON CONFLICT DO UPDATE
has a DB backstop against concurrent writes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Delete lower-id duplicates, keeping the highest id for each key triple.
    op.execute(
        sa.text(
            """
            DELETE FROM slot_extractions
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM slot_extractions
                GROUP BY conversation_id, tool_id, field_name
            )
            """
        )
    )

    op.create_unique_constraint(
        "uq_slot_extraction_key",
        "slot_extractions",
        ["conversation_id", "tool_id", "field_name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_slot_extraction_key", "slot_extractions", type_="unique")
