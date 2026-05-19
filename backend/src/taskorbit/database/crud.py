"""CRUD operations for database models."""

from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ConversationMessage, User

logger = structlog.get_logger()


# ============ USER CRUD ============


async def get_user(db: AsyncSession, user_id: int) -> User | None:
    """Get a user by ID."""
    try:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.error("get_user_failed", error=str(e))
        return None


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Get a user by email."""
    try:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.error("get_user_by_email_failed", error=str(e))
        return None


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    """Get a user by username."""
    try:
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.error("get_user_by_username_failed", error=str(e))
        return None


async def get_users(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[User]:
    """Get all users with pagination."""
    try:
        result = await db.execute(select(User).offset(skip).limit(limit))
        return list(result.scalars().all())
    except SQLAlchemyError as e:
        logger.error("get_users_failed", error=str(e))
        return []


async def create_user(
    db: AsyncSession, username: str, email: str, hashed_password: str, is_active: bool = True
) -> User | None:
    """Create a new user."""
    try:
        db_user = User(
            username=username, email=email, hashed_password=hashed_password, is_active=is_active
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except SQLAlchemyError as e:
        logger.error("create_user_failed", error=str(e))
        await db.rollback()
        return None


async def update_user(
    db: AsyncSession,
    user_id: int,
    username: str | None = None,
    email: str | None = None,
    is_active: bool | None = None,
) -> User | None:
    """Update an existing user."""
    try:
        user = await get_user(db, user_id)
        if not user:
            return None

        if username is not None:
            user.username = username
        if email is not None:
            user.email = email
        if is_active is not None:
            user.is_active = is_active

        user.updated_at = datetime.now()
        await db.commit()
        await db.refresh(user)
        return user
    except SQLAlchemyError as e:
        logger.error("update_user_failed", error=str(e))
        await db.rollback()
        return None


async def delete_user(db: AsyncSession, user_id: int) -> bool:
    """Delete a user by ID."""
    try:
        user = await get_user(db, user_id)
        if not user:
            return False
        await db.delete(user)
        await db.commit()
        return True
    except SQLAlchemyError as e:
        logger.error("delete_user_failed", error=str(e))
        await db.rollback()
        return False


# ============ CONVERSATION MESSAGE CRUD ============


async def get_conversation_message(db: AsyncSession, message_id: int) -> ConversationMessage | None:
    """Get a conversation message by ID."""
    try:
        result = await db.execute(
            select(ConversationMessage).where(ConversationMessage.id == message_id)
        )
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.error("get_conversation_message_failed", error=str(e))
        return None


async def get_messages_by_conversation(
    db: AsyncSession, conversation_id: str, skip: int = 0, limit: int = 100
) -> list[ConversationMessage]:
    """Get all messages for a conversation."""
    try:
        result = await db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())
    except SQLAlchemyError as e:
        logger.error("get_messages_by_conversation_failed", error=str(e))
        return []


async def get_messages_by_user(
    db: AsyncSession, user_id: int, skip: int = 0, limit: int = 100
) -> list[ConversationMessage]:
    """Get all messages for a user."""
    try:
        result = await db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.user_id == user_id)
            .order_by(ConversationMessage.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())
    except SQLAlchemyError as e:
        logger.error("get_messages_by_user_failed", error=str(e))
        return []


async def create_conversation_message(
    db: AsyncSession, conversation_id: str, role: str, content: str, user_id: int | None = None
) -> ConversationMessage | None:
    """Create a new conversation message."""
    try:
        db_message = ConversationMessage(
            conversation_id=conversation_id, user_id=user_id, role=role, content=content
        )
        db.add(db_message)
        await db.commit()
        await db.refresh(db_message)
        return db_message
    except SQLAlchemyError as e:
        logger.error("create_conversation_message_failed", error=str(e))
        await db.rollback()
        return None


async def delete_conversation_message(db: AsyncSession, message_id: int) -> bool:
    """Delete a conversation message by ID."""
    try:
        message = await get_conversation_message(db, message_id)
        if not message:
            return False
        await db.delete(message)
        await db.commit()
        return True
    except SQLAlchemyError as e:
        logger.error("delete_conversation_message_failed", error=str(e))
        await db.rollback()
        return False


# ============ CONVERSATION HELPERS ============


async def get_conversation_messages_formatted(db: AsyncSession, conversation_id: str) -> list[dict]:
    """
    Get all messages for a conversation formatted as dicts.
    Returns a list of dicts with role, content, user_id, and created_at.
    """
    try:
        messages = await get_messages_by_conversation(db, conversation_id)
        return [
            {
                "role": m.role,
                "content": m.content,
                "user_id": m.user_id,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]
    except SQLAlchemyError as e:
        logger.error("get_conversation_messages_formatted_failed", error=str(e))
        return []
