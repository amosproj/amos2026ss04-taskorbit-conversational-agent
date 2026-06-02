"""Standalone seed script — safe to run any number of times.

Re-inserts missing default agent templates and the dummy dev user without
touching the Alembic migration chain. Uses INSERT ... ON CONFLICT DO NOTHING
so existing records are never overwritten.

Usage:
    cd backend
    poetry run python scripts/seed_defaults.py
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Ensure the src package is on the path when run from backend/
sys.path.insert(0, "src")

from taskorbit.config import get_settings
from taskorbit.database.seed_data import DEFAULT_AGENT_TEMPLATES, DEFAULT_USERS
from taskorbit.logging.setup import get_logger

logger = get_logger(__name__)


async def seed(db: AsyncSession) -> None:
    # ── Default agent templates ──────────────────────────────────────────────
    inserted_templates = 0
    for t in DEFAULT_AGENT_TEMPLATES:
        result = await db.execute(
            text(
                "INSERT INTO default_agent_templates (id, name, config, is_active) "
                "VALUES (:id, :name, CAST(:config AS JSON), :is_active) "
                "ON CONFLICT (id) DO UPDATE SET "
                "  name = EXCLUDED.name, "
                "  config = EXCLUDED.config, "
                "  is_active = EXCLUDED.is_active"
            ),
            {
                "id": t["id"],
                "name": t["name"],
                "config": __import__("json").dumps(t["config"]),
                "is_active": t["is_active"],
            },
        )
        inserted_templates += 1
        logger.info("template_upserted", id=t["id"])

    # ── Dummy dev user ───────────────────────────────────────────────────────
    inserted_users = 0
    for u in DEFAULT_USERS:
        result = await db.execute(
            text(
                "INSERT INTO users (username, email, hashed_password, is_active) "
                "VALUES (:username, :email, :hashed_password, :is_active) "
                "ON CONFLICT (email) DO NOTHING"
            ),
            {
                "username": u["username"],
                "email": u["email"],
                "hashed_password": u["hashed_password"],
                "is_active": u["is_active"],
            },
        )
        if result.rowcount:
            inserted_users += 1
            logger.info("user_seeded", username=u["username"])
        else:
            logger.info("user_already_exists", username=u["username"])

    await db.commit()

    print(
        f"\nSeed complete — "
        f"{inserted_templates}/{len(DEFAULT_AGENT_TEMPLATES)} templates upserted, "
        f"{inserted_users}/{len(DEFAULT_USERS)} users inserted (skipped if already exist)."
    )


async def main() -> None:
    settings = get_settings()
    # Ensure the async psycopg v3 driver is used regardless of what the
    # config URL specifies (it may use the bare 'postgresql://' scheme).
    url = settings.database_url.replace("postgresql://", "postgresql+psycopg://").replace(
        "postgres://", "postgresql+psycopg://"
    )
    engine = create_async_engine(url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        await seed(db)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
