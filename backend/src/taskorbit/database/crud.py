"""CRUD operations for database models."""

from datetime import datetime

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .models import ChatHistory, User

logger = structlog.get_logger()


# ============ USER CRUD ============


def get_user(db: Session, user_id: int) -> User | None:
    """Get a user by ID."""
    try:
        return db.query(User).filter(User.id == user_id).first()
    except SQLAlchemyError as e:
        logger.error("get_user_failed", error=str(e))
        return None


def get_user_by_email(db: Session, email: str) -> User | None:
    """Get a user by email."""
    try:
        return db.query(User).filter(User.email == email).first()
    except SQLAlchemyError as e:
        logger.error("get_user_by_email_failed", error=str(e))
        return None


def get_user_by_username(db: Session, username: str) -> User | None:
    """Get a user by username."""
    try:
        return db.query(User).filter(User.username == username).first()
    except SQLAlchemyError as e:
        logger.error("get_user_by_username_failed", error=str(e))
        return None


def get_users(db: Session, skip: int = 0, limit: int = 100) -> list[User]:
    """Get all users with pagination."""
    try:
        return db.query(User).offset(skip).limit(limit).all()
    except SQLAlchemyError as e:
        logger.error("get_users_failed", error=str(e))
        return []


def create_user(
    db: Session, username: str, email: str, hashed_password: str, is_active: bool = True
) -> User | None:
    """Create a new user."""
    try:
        db_user = User(
            username=username, email=email, hashed_password=hashed_password, is_active=is_active
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user
    except SQLAlchemyError as e:
        logger.error("create_user_failed", error=str(e))
        db.rollback()
        return None


def update_user(
    db: Session,
    user_id: int,
    username: str | None = None,
    email: str | None = None,
    is_active: bool | None = None,
) -> User | None:
    """Update an existing user."""
    try:
        user = get_user(db, user_id)
        if not user:
            return None

        if username is not None:
            user.username = username
        if email is not None:
            user.email = email
        if is_active is not None:
            user.is_active = is_active

        user.updated_at = datetime.now()
        db.commit()
        db.refresh(user)
        return user
    except SQLAlchemyError as e:
        logger.error("update_user_failed", error=str(e))
        db.rollback()
        return None


def delete_user(db: Session, user_id: int) -> bool:
    """Delete a user by ID."""
    try:
        user = get_user(db, user_id)
        if not user:
            return False
        db.delete(user)
        db.commit()
        return True
    except SQLAlchemyError as e:
        logger.error("delete_user_failed", error=str(e))
        db.rollback()
        return False


# ============ CHAT HISTORY CRUD ============


def get_chat_history(db: Session, history_id: int) -> ChatHistory | None:
    """Get a chat history entry by ID."""
    try:
        return db.query(ChatHistory).filter(ChatHistory.id == history_id).first()
    except SQLAlchemyError as e:
        logger.error("get_chat_history_failed", error=str(e))
        return None


def get_chat_histories_by_user(
    db: Session, user_id: int, skip: int = 0, limit: int = 100
) -> list[ChatHistory]:
    """Get all chat history entries for a user."""
    try:
        return (
            db.query(ChatHistory)
            .filter(ChatHistory.user_id == user_id)
            .order_by(ChatHistory.timestamp.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
    except SQLAlchemyError as e:
        logger.error("get_chat_histories_by_user_failed", error=str(e))
        return []


def get_chat_histories_by_conversation(
    db: Session, conversation_id: str, skip: int = 0, limit: int = 100
) -> list[ChatHistory]:
    """Get all chat history entries for a conversation."""
    try:
        return (
            db.query(ChatHistory)
            .filter(ChatHistory.conversation_id == conversation_id)
            .order_by(ChatHistory.timestamp.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )
    except SQLAlchemyError as e:
        logger.error("get_chat_histories_by_conversation_failed", error=str(e))
        return []


def create_chat_history(
    db: Session, user_id: int, conversation_id: str, role: str, message: str
) -> ChatHistory | None:
    """Create a new chat history entry."""
    try:
        db_entry = ChatHistory(
            user_id=user_id, conversation_id=conversation_id, role=role, message=message
        )
        db.add(db_entry)
        db.commit()
        db.refresh(db_entry)
        return db_entry
    except SQLAlchemyError as e:
        logger.error("create_chat_history_failed", error=str(e))
        db.rollback()
        return None


def delete_chat_history(db: Session, history_id: int) -> bool:
    """Delete a chat history entry by ID."""
    try:
        entry = get_chat_history(db, history_id)
        if not entry:
            return False
        db.delete(entry)
        db.commit()
        return True
    except SQLAlchemyError as e:
        logger.error("delete_chat_history_failed", error=str(e))
        db.rollback()
        return False


# ============ CONVERSATION HELPERS ============


def get_conversation_messages_with_history(db: Session, conversation_id: str) -> list[dict]:
    """
    Get all messages for a conversation.
    Returns a list of dicts with role and content.
    """
    try:
        messages = (
            db.query(ChatHistory)
            .filter(ChatHistory.conversation_id == conversation_id)
            .order_by(ChatHistory.timestamp.asc())
            .all()
        )
        return [{"role": m.role, "content": m.message} for m in messages]
    except SQLAlchemyError as e:
        logger.error("get_conversation_messages_with_history_failed", error=str(e))
        return []
