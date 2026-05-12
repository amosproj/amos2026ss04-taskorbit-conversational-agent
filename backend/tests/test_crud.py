"""Unit tests for CRUD operations."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from taskorbit.database.models import Base
from taskorbit.database.crud import (
    create_user, get_user, get_user_by_email, get_user_by_username,
    get_users, update_user, delete_user,
    create_conversation_message, get_messages_by_conversation,
    get_messages_by_user, delete_conversation_message
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


class TestConversationMessageCRUD:
    """Tests for ConversationMessage CRUD operations."""

    def test_create_conversation_message(self, db_session):
        user = create_user(db_session, username="msguser", email="msg@example.com", hashed_password="hash")
        message = create_conversation_message(
            db_session,
            conversation_id="conv-123",
            role="user",
            content="Hello, world!",
            user_id=user.id
        )
        assert message is not None
        assert message.id is not None
        assert message.conversation_id == "conv-123"
        assert message.role == "user"
        assert message.content == "Hello, world!"
        assert message.user_id == user.id

    def test_get_messages_by_conversation(self, db_session):
        user = create_user(db_session, username="convuser", email="conv@example.com", hashed_password="hash")
        for i in range(3):
            create_conversation_message(
                db_session,
                conversation_id="conv-456",
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}",
                user_id=user.id if i % 2 == 0 else None
            )
        messages = get_messages_by_conversation(db_session, "conv-456")
        assert len(messages) >= 3

    def test_get_messages_by_user(self, db_session):
        user = create_user(db_session, username="user123", email="user123@example.com", hashed_password="hash")
        other_user = create_user(db_session, username="other", email="other@example.com", hashed_password="hash")
        
        for i in range(3):
            create_conversation_message(
                db_session,
                conversation_id=f"conv-{i}",
                role="user",
                content=f"Message {i}",
                user_id=user.id
            )
        create_conversation_message(
            db_session,
            conversation_id="conv-other",
            role="user",
            content="Other user message",
            user_id=other_user.id
        )
        
        user_messages = get_messages_by_user(db_session, user.id)
        assert len(user_messages) >= 3
        
        for msg in user_messages:
            assert msg.user_id == user.id

    def test_delete_conversation_message(self, db_session):
        user = create_user(db_session, username="deluser", email="del@example.com", hashed_password="hash")
        message = create_conversation_message(
            db_session,
            conversation_id="conv-del",
            role="user",
            content="Delete me",
            user_id=user.id
        )
        message_id = message.id
        result = delete_conversation_message(db_session, message_id)
        assert result is True
        deleted = get_messages_by_conversation(db_session, "conv-del")
        assert len(deleted) == 0