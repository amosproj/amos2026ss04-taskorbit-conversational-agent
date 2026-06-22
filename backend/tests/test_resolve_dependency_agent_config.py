"""Tests for logical-id lookup in resolve_dependency_agent_config."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from taskorbit.database.crud import resolve_dependency_agent_config
from taskorbit.database.models import AgentConfiguration, Base, User

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        user = User(
            id=1,
            username="dev",
            email="dev@example.com",
            hashed_password="hash",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_dependency_agent_config_finds_by_config_id_key(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        AgentConfiguration(
            id="db-uuid-c",
            name="Identity",
            config={
                "id": "identity-verification",
                "name": "Identity Verification",
                "persona": "VERIFY",
                "greeting": "g",
            },
            user_id=None,
        )
    )
    await db_session.commit()

    resolved = await resolve_dependency_agent_config(db_session, "identity-verification", user_id=1)

    assert resolved is not None
    assert resolved.id == "identity-verification"
    assert resolved.name == "Identity Verification"
