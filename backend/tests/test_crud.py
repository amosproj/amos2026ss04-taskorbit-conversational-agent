"""Unit tests for CRUD operations."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from taskorbit.database.crud import (
    create_conversation_message,
    create_user,
    delete_conversation_message,
    delete_user,
    get_messages_by_conversation,
    get_messages_by_user,
    get_user,
    get_user_by_email,
    get_user_by_username,
    get_users,
    update_user,
)
from taskorbit.database.models import Base

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


class TestUserCRUD:
    """Tests for User CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_user(self, db_session):
        user = await create_user(
            db_session, username="testuser", email="test@example.com", hashed_password="fakehash123"
        )
        assert user is not None
        assert user.id is not None
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_get_user(self, db_session):
        created = await create_user(
            db_session, username="getuser", email="get@example.com", hashed_password="hash"
        )
        fetched = await get_user(db_session, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.username == "getuser"

    @pytest.mark.asyncio
    async def test_get_user_by_email(self, db_session):
        await create_user(
            db_session, username="emailuser", email="unique@example.com", hashed_password="hash"
        )
        found = await get_user_by_email(db_session, "unique@example.com")
        assert found is not None
        assert found.email == "unique@example.com"

    @pytest.mark.asyncio
    async def test_get_user_by_username(self, db_session):
        await create_user(
            db_session, username="uniqueuser", email="u@example.com", hashed_password="hash"
        )
        found = await get_user_by_username(db_session, "uniqueuser")
        assert found is not None
        assert found.username == "uniqueuser"

    @pytest.mark.asyncio
    async def test_get_users(self, db_session):
        for i in range(3):
            await create_user(
                db_session, username=f"user{i}", email=f"user{i}@test.com", hashed_password="hash"
            )
        users = await get_users(db_session, skip=0, limit=10)
        assert len(users) >= 3

    @pytest.mark.asyncio
    async def test_update_user(self, db_session):
        user = await create_user(
            db_session, username="oldname", email="old@example.com", hashed_password="hash"
        )
        updated = await update_user(
            db_session, user.id, username="newname", email="new@example.com"
        )
        assert updated is not None
        assert updated.username == "newname"
        assert updated.email == "new@example.com"

    @pytest.mark.asyncio
    async def test_delete_user(self, db_session):
        user = await create_user(
            db_session, username="todelete", email="delete@example.com", hashed_password="hash"
        )
        user_id = user.id
        result = await delete_user(db_session, user_id)
        assert result is True
        deleted = await get_user(db_session, user_id)
        assert deleted is None


class TestConversationMessageCRUD:
    """Tests for ConversationMessage CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_conversation_message(self, db_session):
        user = await create_user(
            db_session, username="msguser", email="msg@example.com", hashed_password="hash"
        )
        message = await create_conversation_message(
            db_session,
            conversation_id="conv-123",
            role="user",
            content="Hello, world!",
            user_id=user.id,
        )
        assert message is not None
        assert message.id is not None
        assert message.conversation_id == "conv-123"
        assert message.role == "user"
        assert message.content == "Hello, world!"
        assert message.user_id == user.id

    @pytest.mark.asyncio
    async def test_get_messages_by_conversation(self, db_session):
        user = await create_user(
            db_session, username="convuser", email="conv@example.com", hashed_password="hash"
        )
        for i in range(3):
            await create_conversation_message(
                db_session,
                conversation_id="conv-456",
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}",
                user_id=user.id if i % 2 == 0 else None,
            )
        messages = await get_messages_by_conversation(db_session, "conv-456")
        assert len(messages) >= 3

    @pytest.mark.asyncio
    async def test_get_messages_by_user(self, db_session):
        user = await create_user(
            db_session, username="user123", email="user123@example.com", hashed_password="hash"
        )
        other_user = await create_user(
            db_session, username="other", email="other@example.com", hashed_password="hash"
        )
        for i in range(3):
            await create_conversation_message(
                db_session,
                conversation_id=f"conv-{i}",
                role="user",
                content=f"Message {i}",
                user_id=user.id,
            )
        await create_conversation_message(
            db_session,
            conversation_id="conv-other",
            role="user",
            content="Other user message",
            user_id=other_user.id,
        )
        user_messages = await get_messages_by_user(db_session, user.id)
        assert len(user_messages) >= 3
        for msg in user_messages:
            assert msg.user_id == user.id

    @pytest.mark.asyncio
    async def test_delete_conversation_message(self, db_session):
        user = await create_user(
            db_session, username="deluser", email="del@example.com", hashed_password="hash"
        )
        message = await create_conversation_message(
            db_session,
            conversation_id="conv-del",
            role="user",
            content="Delete me",
            user_id=user.id,
        )
        message_id = message.id
        result = await delete_conversation_message(db_session, message_id)
        assert result is True
        deleted = await get_messages_by_conversation(db_session, "conv-del")
        assert len(deleted) == 0
