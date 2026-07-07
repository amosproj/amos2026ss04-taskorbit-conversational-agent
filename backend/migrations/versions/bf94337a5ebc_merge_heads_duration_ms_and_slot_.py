"""merge heads: duration_ms and slot_extractions dedup

Revision ID: bf94337a5ebc
Revises: a1b2c3d4e5f6, f7a8b9c0d1e2
Create Date: 2026-07-07 21:00:47.240144

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "bf94337a5ebc"
down_revision: str | Sequence[str] | None = ("a1b2c3d4e5f6", "f7a8b9c0d1e2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
