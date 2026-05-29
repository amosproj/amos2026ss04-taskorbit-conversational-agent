"""CRUD operations for database models."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from taskorbit.logging.setup import get_logger

from .models import AgentConfiguration, ConversationMessage, DefaultAgentTemplate, User, UserAgent

logger = get_logger(__name__)


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


# ============ DEFAULT AGENT TEMPLATES CRUD ============


async def list_default_agent_templates(
    db: AsyncSession, active_only: bool = True
) -> list[DefaultAgentTemplate]:
    try:
        query = select(DefaultAgentTemplate)
        if active_only:
            query = query.where(DefaultAgentTemplate.is_active.is_(True))
        result = await db.execute(query.order_by(DefaultAgentTemplate.name))
        return list(result.scalars().all())
    except SQLAlchemyError as e:
        logger.error("list_default_agent_templates_failed", error=str(e))
        return []


async def get_default_agent_template(
    db: AsyncSession, template_id: str
) -> DefaultAgentTemplate | None:
    try:
        result = await db.execute(
            select(DefaultAgentTemplate).where(DefaultAgentTemplate.id == template_id)
        )
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.error("get_default_agent_template_failed", template_id=template_id, error=str(e))
        return None


# ============ USER AGENTS CRUD ============


async def create_user_agents_from_templates(db: AsyncSession, user_id: int) -> list[UserAgent]:
    """Clone all active default templates into user_agents for a new user.

    The first template is marked is_default=True. Safe to call once per user
    on registration.
    """
    try:
        templates = await list_default_agent_templates(db, active_only=True)
        if not templates:
            logger.warning("create_user_agents_from_templates_no_templates", user_id=user_id)
            return []

        agents: list[UserAgent] = []
        for i, tpl in enumerate(templates):
            agent = UserAgent(
                id=uuid4().hex,
                user_id=user_id,
                template_id=tpl.id,
                name=tpl.name,
                config=tpl.config,
                is_default=(i == 0),
            )
            db.add(agent)
            agents.append(agent)

        await db.commit()
        for agent in agents:
            await db.refresh(agent)

        logger.info(
            "user_agents_created_from_templates",
            user_id=user_id,
            count=len(agents),
        )
        return agents
    except SQLAlchemyError as e:
        logger.error("create_user_agents_from_templates_failed", user_id=user_id, error=str(e))
        await db.rollback()
        return []


async def list_user_agents(db: AsyncSession, user_id: int) -> list[UserAgent]:
    try:
        result = await db.execute(
            select(UserAgent)
            .where(UserAgent.user_id == user_id)
            .order_by(UserAgent.is_default.desc(), UserAgent.created_at)
        )
        return list(result.scalars().all())
    except SQLAlchemyError as e:
        logger.error("list_user_agents_failed", user_id=user_id, error=str(e))
        return []


async def get_user_agent(db: AsyncSession, agent_id: str, user_id: int) -> UserAgent | None:
    try:
        result = await db.execute(
            select(UserAgent).where(UserAgent.id == agent_id, UserAgent.user_id == user_id)
        )
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.error("get_user_agent_failed", agent_id=agent_id, error=str(e))
        return None


async def update_user_agent(
    db: AsyncSession,
    agent_id: str,
    user_id: int,
    name: str | None = None,
    config: dict | None = None,
    is_default: bool | None = None,
) -> UserAgent | None:
    try:
        agent = await get_user_agent(db, agent_id, user_id)
        if not agent:
            return None
        if name is not None:
            agent.name = name
        if config is not None:
            agent.config = config
        if is_default is not None:
            agent.is_default = is_default
        agent.updated_at = datetime.now()
        await db.commit()
        await db.refresh(agent)
        return agent
    except SQLAlchemyError as e:
        logger.error("update_user_agent_failed", agent_id=agent_id, error=str(e))
        await db.rollback()
        return None


async def delete_user_agent(db: AsyncSession, agent_id: str, user_id: int) -> bool:
    try:
        agent = await get_user_agent(db, agent_id, user_id)
        if not agent:
            return False
        await db.delete(agent)
        await db.commit()
        return True
    except SQLAlchemyError as e:
        logger.error("delete_user_agent_failed", agent_id=agent_id, error=str(e))
        await db.rollback()
        return False


async def copy_on_write_user_agent(
    db: AsyncSession,
    user_id: int,
    template_id: str,
    name: str | None = None,
    config_updates: dict | None = None,
) -> UserAgent | None:
    """Clone a default template into user_agents and apply updates — copy-on-write.

    Rules:
    - If the user already has a copy of this template → update that copy.
    - If not → clone the template and apply the updates to the new copy.
    - The default_agent_templates row is never modified.
    """
    try:
        # Check if the user already owns a copy of this template.
        result = await db.execute(
            select(UserAgent).where(
                UserAgent.user_id == user_id,
                UserAgent.template_id == template_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update the existing user copy.
            if name is not None:
                existing.name = name
            if config_updates is not None:
                merged = {**existing.config, **config_updates}
                existing.config = merged
            existing.updated_at = datetime.now()
            await db.commit()
            await db.refresh(existing)
            logger.info("user_agent_updated", agent_id=existing.id, user_id=user_id)
            return existing

        # No copy yet — fetch the template and clone it.
        template = await get_default_agent_template(db, template_id)
        if not template:
            logger.warning("copy_on_write_template_not_found", template_id=template_id)
            return None

        cloned_config = {**template.config, **(config_updates or {})}
        agent = UserAgent(
            id=uuid4().hex,
            user_id=user_id,
            template_id=template_id,
            name=name or template.name,
            config=cloned_config,
            is_default=False,
        )
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
        logger.info(
            "user_agent_cloned_from_template",
            agent_id=agent.id,
            template_id=template_id,
            user_id=user_id,
        )
        return agent
    except SQLAlchemyError as e:
        logger.error(
            "copy_on_write_user_agent_failed",
            template_id=template_id,
            user_id=user_id,
            error=str(e),
        )
        await db.rollback()
        return None


async def list_user_agents_merged(db: AsyncSession, user_id: int) -> list[dict]:
    """Return all agents for a user — their customised copies + uncustomised templates.

    Each entry carries an extra key ``is_customized`` so the frontend knows
    whether the user has already edited that agent.
    """
    user_agents = await list_user_agents(db, user_id)
    templates = await list_default_agent_templates(db, active_only=True)

    customised_template_ids = {a.template_id for a in user_agents if a.template_id}

    merged: list[dict] = []

    # User's customised copies first.
    for agent in user_agents:
        merged.append(
            {
                "id": agent.id,
                "template_id": agent.template_id,
                "name": agent.name,
                "config": agent.config,
                "is_default": agent.is_default,
                "is_customized": True,
                "created_at": agent.created_at,
                "updated_at": agent.updated_at,
            }
        )

    # Templates the user hasn't touched yet.
    for tpl in templates:
        if tpl.id not in customised_template_ids:
            merged.append(
                {
                    "id": tpl.id,
                    "template_id": tpl.id,
                    "name": tpl.name,
                    "config": tpl.config,
                    "is_default": False,
                    "is_customized": False,
                    "created_at": tpl.created_at,
                    "updated_at": None,
                }
            )

    return merged
