"""Integration tests for transitive dependency enrichment in CRUD."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from taskorbit.database.crud import enrich_request_dependency_configs
from taskorbit.database.models import Base
from taskorbit.types import AgentConfig, ConversationRequest, Message, MessageRole

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session():
    """Create a fresh async database for each test."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_enrich_request_dependency_configs_transitive(db_session: AsyncSession) -> None:
    # Set up: A -> B -> C

    # Agent C
    config_c = {
        "id": "agent-c",
        "name": "C",
        "persona": "p",
        "greeting": "g",
        "workflow_dependencies": [],
    }
    # Agent B
    config_b = {
        "id": "agent-b",
        "name": "B",
        "persona": "p",
        "greeting": "g",
        "workflow_dependencies": ["agent-c"],
    }
    # Agent A (entry)
    config_a = AgentConfig(
        id="agent-a", name="A", persona="p", greeting="g", workflow_dependencies=["agent-b"]
    )

    from taskorbit.database.models import AgentConfiguration

    db_session.add(AgentConfiguration(id="agent-c-uuid", name="C", config=config_c, user_id=None))
    db_session.add(AgentConfiguration(id="agent-b-uuid", name="B", config=config_b, user_id=None))
    await db_session.commit()

    request = ConversationRequest(
        conversation_id="conv-1",
        messages=[Message(role=MessageRole.USER, content="hi")],
        agent_config=config_a,
    )

    # Enrich
    enriched = await enrich_request_dependency_configs(request, db_session, user_id=1)

    # Verify both B and C are loaded
    assert "agent-b" in enriched.dependency_configs
    assert "agent-c" in enriched.dependency_configs
    assert enriched.dependency_configs["agent-b"].name == "B"
    assert enriched.dependency_configs["agent-c"].name == "C"
