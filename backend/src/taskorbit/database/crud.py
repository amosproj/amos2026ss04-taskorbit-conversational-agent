"""CRUD operations for database models."""

from sqlalchemy.orm import Session
from datetime import datetime
from .models import User, ChatHistory, Conversation


# ============ USER CRUD ============

def get_user(db: Session, user_id: int) -> User | None:
    """Get a user by ID."""
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_email(db: Session, email: str) -> User | None:
    """Get a user by email."""
    return db.query(User).filter(User.email == email).first()


def get_user_by_username(db: Session, username: str) -> User | None:
    """Get a user by username."""
    return db.query(User).filter(User.username == username).first()


def get_users(db: Session, skip: int = 0, limit: int = 100) -> list[User]:
    """Get all users with pagination."""
    return db.query(User).offset(skip).limit(limit).all()


def create_user(
    db: Session,
    username: str,
    email: str,
    hashed_password: str,
    is_active: bool = True
) -> User:
    """Create a new user."""
    db_user = User(
        username=username,
        email=email,
        hashed_password=hashed_password,
        is_active=is_active
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def update_user(
    db: Session,
    user_id: int,
    username: str | None = None,
    email: str | None = None,
    is_active: bool | None = None
) -> User | None:
    """Update an existing user."""
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


def delete_user(db: Session, user_id: int) -> bool:
    """Delete a user by ID."""
    user = get_user(db, user_id)
    if not user:
        return False
    db.delete(user)
    db.commit()
    return True


# ============ CHAT HISTORY CRUD ============

def get_chat_history(db: Session, history_id: int) -> ChatHistory | None:
    """Get a chat history entry by ID."""
    return db.query(ChatHistory).filter(ChatHistory.id == history_id).first()


def get_chat_histories_by_user(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 100
) -> list[ChatHistory]:
    """Get all chat history entries for a user."""
    return (
        db.query(ChatHistory)
        .filter(ChatHistory.user_id == user_id)
        .order_by(ChatHistory.timestamp.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_chat_histories_by_conversation(
    db: Session,
    conversation_id: str,
    skip: int = 0,
    limit: int = 100
) -> list[ChatHistory]:
    """Get all chat history entries for a conversation."""
    return (
        db.query(ChatHistory)
        .filter(ChatHistory.conversation_id == conversation_id)
        .order_by(ChatHistory.timestamp.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def create_chat_history(
    db: Session,
    user_id: int,
    conversation_id: str,
    role: str,
    message: str
) -> ChatHistory:
    """Create a new chat history entry."""
    db_entry = ChatHistory(
        user_id=user_id,
        conversation_id=conversation_id,
        role=role,
        message=message
    )
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return db_entry


def delete_chat_history(db: Session, history_id: int) -> bool:
    """Delete a chat history entry by ID."""
    entry = get_chat_history(db, history_id)
    if not entry:
        return False
    db.delete(entry)
    db.commit()
    return True


# ============ CONVERSATION HELPERS ============

def get_conversation_messages_with_history(
    db: Session,
    conversation_id: str
) -> list[dict]:
    """
    Get all messages for a conversation.
    Returns a list of dicts with role and content.
    """
    messages = (
        db.query(ChatHistory)
        .filter(ChatHistory.conversation_id == conversation_id)
        .order_by(ChatHistory.timestamp.asc())
        .all()
    )
    return [{"role": m.role, "content": m.message} for m in messages]