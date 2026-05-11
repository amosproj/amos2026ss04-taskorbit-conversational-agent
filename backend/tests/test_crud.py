"""Unit tests for CRUD operations."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from taskorbit.database.models import Base
from taskorbit.database.crud import (
    create_user, get_user, get_user_by_email, get_user_by_username,
    get_users, update_user, delete_user,
    create_chat_history, get_chat_histories_by_user,
    get_chat_histories_by_conversation, delete_chat_history
)


# Use in-memory SQLite for testing
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


class TestUserCRUD:
    """Tests for User CRUD operations."""

    def test_create_user(self, db_session):
        user = create_user(
            db_session,
            username="testuser",
            email="test@example.com",
            hashed_password="fakehash123"
        )
        assert user is not None
        assert user.id is not None
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.is_active is True

    def test_get_user(self, db_session):
        created = create_user(
            db_session,
            username="getuser",
            email="get@example.com",
            hashed_password="hash"
        )
        fetched = get_user(db_session, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.username == "getuser"

    def test_get_user_by_email(self, db_session):
        create_user(db_session, username="emailuser", email="unique@example.com", hashed_password="hash")
        found = get_user_by_email(db_session, "unique@example.com")
        assert found is not None
        assert found.email == "unique@example.com"

    def test_get_user_by_username(self, db_session):
        create_user(db_session, username="uniqueuser", email="u@example.com", hashed_password="hash")
        found = get_user_by_username(db_session, "uniqueuser")
        assert found is not None
        assert found.username == "uniqueuser"

    def test_get_users(self, db_session):
        for i in range(3):
            create_user(db_session, username=f"user{i}", email=f"user{i}@test.com", hashed_password="hash")
        users = get_users(db_session, skip=0, limit=10)
        assert len(users) >= 3

    def test_update_user(self, db_session):
        user = create_user(db_session, username="oldname", email="old@example.com", hashed_password="hash")
        updated = update_user(db_session, user.id, username="newname", email="new@example.com")
        assert updated is not None
        assert updated.username == "newname"
        assert updated.email == "new@example.com"

    def test_delete_user(self, db_session):
        user = create_user(db_session, username="todelete", email="delete@example.com", hashed_password="hash")
        user_id = user.id
        result = delete_user(db_session, user_id)
        assert result is True
        deleted = get_user(db_session, user_id)
        assert deleted is None


class TestChatHistoryCRUD:
    """Tests for ChatHistory CRUD operations."""

    def test_create_chat_history(self, db_session):
        user = create_user(db_session, username="chatuser", email="chat@example.com", hashed_password="hash")
        entry = create_chat_history(
            db_session,
            user_id=user.id,
            conversation_id="conv-123",
            role="user",
            message="Hello, world!"
        )
        assert entry is not None
        assert entry.id is not None
        assert entry.user_id == user.id
        assert entry.conversation_id == "conv-123"
        assert entry.role == "user"
        assert entry.message == "Hello, world!"

    def test_get_chat_histories_by_user(self, db_session):
        user = create_user(db_session, username="multichat", email="multi@example.com", hashed_password="hash")
        for i in range(3):
            create_chat_history(db_session, user.id, f"conv-{i}", "user", f"Message {i}")
        histories = get_chat_histories_by_user(db_session, user.id)
        assert len(histories) >= 3

    def test_delete_chat_history(self, db_session):
        user = create_user(db_session, username="delchatuser", email="delchat@example.com", hashed_password="hash")
        entry = create_chat_history(db_session, user.id, "conv-del", "user", "Delete me")
        entry_id = entry.id
        result = delete_chat_history(db_session, entry_id)
        assert result is True