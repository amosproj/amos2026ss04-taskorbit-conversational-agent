# update and delete CRUD tests belong to the update-and-delete-configuration ticket and are written by that ticket's owner.

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from taskorbit.database.crud import (
    create_agent_configuration,
    get_agent_configuration,
    list_agent_configurations,
)
from taskorbit.database.models import Base

TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session():
    """Create a fresh database for each test."""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


class TestAgentConfigurationCRUD:
    """Tests for AgentConfiguration CRUD operations."""

    def test_create_agent_configuration(self, db_session):
        config = {"model": "gpt-4", "temperature": 0.7}
        result = create_agent_configuration(db_session, name="test-config", config=config)
        assert result is not None
        assert isinstance(result.id, str)
        assert len(result.id) > 0
        assert result.name == "test-config"
        assert result.config == config

    def test_get_agent_configuration(self, db_session):
        created = create_agent_configuration(
            db_session, name="get-config", config={"provider": "openai"}
        )
        fetched = get_agent_configuration(db_session, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == created.name
        assert fetched.config == created.config

    def test_get_agent_configuration_not_found(self, db_session):
        result = get_agent_configuration(db_session, "nonexistent-id")
        assert result is None

    def test_list_agent_configurations(self, db_session):
        names = ["alpha", "beta", "gamma"]
        for name in names:
            create_agent_configuration(db_session, name=name, config={"name": name})
        results = list_agent_configurations(db_session)
        assert len(results) == 3
        for i in range(len(results) - 1):
            assert results[i].created_at >= results[i + 1].created_at

    def test_list_agent_configurations_empty(self, db_session):
        results = list_agent_configurations(db_session)
        assert results == []
