"""CRUD operations for database models."""

from datetime import datetime
from uuid import uuid4

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .models import AgentConfiguration, ConversationMessage, User

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


# ============ CONVERSATION MESSAGE CRUD ============


def get_conversation_message(db: Session, message_id: int) -> ConversationMessage | None:
    """Get a conversation message by ID."""
    try:
        return db.query(ConversationMessage).filter(ConversationMessage.id == message_id).first()
    except SQLAlchemyError as e:
        logger.error("get_conversation_message_failed", error=str(e))
        return None


def get_messages_by_conversation(
    db: Session, conversation_id: str, skip: int = 0, limit: int = 100
) -> list[ConversationMessage]:
    """Get all messages for a conversation."""
    try:
        return (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )
    except SQLAlchemyError as e:
        logger.error("get_messages_by_conversation_failed", error=str(e))
        return []


def get_messages_by_user(
    db: Session, user_id: int, skip: int = 0, limit: int = 100
) -> list[ConversationMessage]:
    """Get all messages for a user."""
    try:
        return (
            db.query(ConversationMessage)
            .filter(ConversationMessage.user_id == user_id)
            .order_by(ConversationMessage.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
    except SQLAlchemyError as e:
        logger.error("get_messages_by_user_failed", error=str(e))
        return []


def create_conversation_message(
    db: Session, conversation_id: str, role: str, content: str, user_id: int | None = None
) -> ConversationMessage | None:
    """Create a new conversation message."""
    try:
        db_message = ConversationMessage(
            conversation_id=conversation_id, user_id=user_id, role=role, content=content
        )
        db.add(db_message)
        db.commit()
        db.refresh(db_message)
        return db_message
    except SQLAlchemyError as e:
        logger.error("create_conversation_message_failed", error=str(e))
        db.rollback()
        return None


def delete_conversation_message(db: Session, message_id: int) -> bool:
    """Delete a conversation message by ID."""
    try:
        message = get_conversation_message(db, message_id)
        if not message:
            return False
        db.delete(message)
        db.commit()
        return True
    except SQLAlchemyError as e:
        logger.error("delete_conversation_message_failed", error=str(e))
        db.rollback()
        return False


# ============ CONVERSATION HELPERS ============


def get_conversation_messages_formatted(db: Session, conversation_id: str) -> list[dict]:
    """
    Get all messages for a conversation formatted as dicts.
    Returns a list of dicts with role, content, user_id, and created_at.
    """
    try:
        messages = get_messages_by_conversation(db, conversation_id)
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


# ============ AGENT CONFIGURATION CRUD ============


def get_agent_configuration(db: Session, config_id: str) -> AgentConfiguration | None:
    try:
        return db.query(AgentConfiguration).filter(AgentConfiguration.id == config_id).first()
    except SQLAlchemyError as e:
        logger.error("get_agent_configuration_failed", error=str(e))
        return None


def list_agent_configurations(
    db: Session, skip: int = 0, limit: int = 100
) -> list[AgentConfiguration]:
    try:
        return (
            db.query(AgentConfiguration)
            .order_by(AgentConfiguration.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
    except SQLAlchemyError as e:
        logger.error("list_agent_configurations_failed", error=str(e))
        return []


def create_agent_configuration(db: Session, name: str, config: dict) -> AgentConfiguration | None:
    try:
        db_config = AgentConfiguration(id=uuid4().hex, name=name, config=config)
        db.add(db_config)
        db.commit()
        db.refresh(db_config)
        return db_config
    except SQLAlchemyError as e:
        logger.error("create_agent_configuration_failed", error=str(e))
        db.rollback()
        return None


def update_agent_configuration(
    db: Session,
    config_id: str,
    name: str | None = None,
    config: dict | None = None,
) -> AgentConfiguration | None:
    try:
        db_config = get_agent_configuration(db, config_id)
        if not db_config:
            return None

        if name is not None:
            db_config.name = name
        if config is not None:
            db_config.config = config

        db_config.updated_at = datetime.now()
        db.commit()
        db.refresh(db_config)
        return db_config
    except SQLAlchemyError as e:
        logger.error("update_agent_configuration_failed", error=str(e))
        db.rollback()
        return None


def delete_agent_configuration(db: Session, config_id: str) -> bool:
    try:
        db_config = get_agent_configuration(db, config_id)
        if not db_config:
            return False
        db.delete(db_config)
        db.commit()
        return True
    except SQLAlchemyError as e:
        logger.error("delete_agent_configuration_failed", error=str(e))
        db.rollback()
        return False
