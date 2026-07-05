"""CRUD operations for database models."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from taskorbit.agent_config_util import agent_config_from_stored_blob
from taskorbit.logging.setup import get_logger
from taskorbit.types import AgentConfig, ConversationRequest, default_persona_constraints

from .models import (
    AgentConfiguration,
    Conversation,
    ConversationMessage,
    DefaultAgentTemplate,
    SlotExtraction,
    ToolExecution,
    User,
)

logger = get_logger(__name__)


def _config_logical_id_matches(logical_id: str):
    """Match workflow logical ids stored in the JSON config blob (agent_id or id)."""
    return or_(
        AgentConfiguration.config["agent_id"].as_string() == logical_id,
        AgentConfiguration.config["id"].as_string() == logical_id,
    )


async def _find_agent_config_by_logical_id(
    db: AsyncSession,
    logical_id: str,
    user_id: int,
) -> AgentConfiguration | None:
    """Look up a saved agent row by logical id, preferring the user's copy."""
    try:
        user_result = await db.execute(
            select(AgentConfiguration)
            .where(
                AgentConfiguration.user_id == user_id,
                _config_logical_id_matches(logical_id),
            )
            .limit(1)
        )
        row = user_result.scalar_one_or_none()
        if row is not None:
            return row

        admin_result = await db.execute(
            select(AgentConfiguration)
            .where(
                AgentConfiguration.user_id.is_(None),
                _config_logical_id_matches(logical_id),
            )
            .limit(1)
        )
        return admin_result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.error(
            "find_agent_config_by_logical_id_failed",
            logical_id=logical_id,
            user_id=user_id,
            error=str(e),
        )
        return None


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


# ============ CONVERSATION CRUD ============


async def get_conversation(db: AsyncSession, conversation_id: str) -> Conversation | None:
    try:
        result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.error("get_conversation_failed", error=str(e))
        return None


async def create_conversation(
    db: AsyncSession, agent_id: str, agent_name: str, id: str | None = None
) -> Conversation | None:
    try:
        conversation = Conversation(
            id=id or str(uuid4()),
            agent_id=agent_id,
            agent_name=agent_name,
            started_at=datetime.now(UTC),
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        logger.info("conversation_created", conversation_id=conversation.id)
        return conversation
    except SQLAlchemyError as e:
        logger.error("create_conversation_failed", error=str(e))
        await db.rollback()
        return None


# ============ SLOT EXTRACTION CRUD ============


async def create_slot_extractions(
    db: AsyncSession,
    conversation_id: str,
    tool_id: str,
    slots: dict,
    user_id: int | None = None,
) -> list[SlotExtraction]:
    """Upsert one row per extracted field, recording which tool extracted it.

    A field is keyed by ``(conversation_id, tool_id, field_name)``: an existing
    row is updated in place, a new field is inserted. Extraction tools fire
    repeatedly over a call with the cumulative slot set, so inserting every time
    floods the history view with duplicate rows (the same field repeated once
    per turn). Upserting keeps a single current value per field.
    """
    if not slots:
        return []
    try:
        field_names = [str(name) for name in slots]
        existing_result = await db.execute(
            select(SlotExtraction).where(
                SlotExtraction.conversation_id == conversation_id,
                SlotExtraction.tool_id == tool_id,
                SlotExtraction.field_name.in_(field_names),
            )
        )
        existing = {row.field_name: row for row in existing_result.scalars().all()}

        extractions: list[SlotExtraction] = []
        for name, value in slots.items():
            field_name = str(name)
            field_value = str(value) if value is not None else None
            row = existing.get(field_name)
            if row is not None:
                row.field_value = field_value
            else:
                row = SlotExtraction(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    tool_id=tool_id,
                    field_name=field_name,
                    field_value=field_value,
                )
                db.add(row)
            extractions.append(row)
        await db.commit()
        for extraction in extractions:
            await db.refresh(extraction)
        logger.info(
            "slot_extractions_saved",
            conversation_id=conversation_id,
            tool_id=tool_id,
            count=len(extractions),
        )
        return extractions
    except SQLAlchemyError as e:
        logger.error("create_slot_extractions_failed", error=str(e))
        await db.rollback()
        return []


async def get_slot_extractions(db: AsyncSession, conversation_id: str) -> list[SlotExtraction]:
    """Return the current slot extractions for a conversation.

    Deduplicated to one row per ``(tool_id, field_name)`` keeping the latest
    value, so conversations recorded before the write-side upsert (which stored
    a new row per turn) still render cleanly in the history view. Fields keep
    their first-seen order.
    """
    try:
        result = await db.execute(
            select(SlotExtraction)
            .where(SlotExtraction.conversation_id == conversation_id)
            .order_by(SlotExtraction.extracted_at.asc())
        )
        rows = list(result.scalars().all())
        latest: dict[tuple[str, str], SlotExtraction] = {}
        for row in rows:
            # Ascending order means a later row overwrites an earlier one, so the
            # dict ends with the most recent value while preserving first-seen order.
            latest[(row.tool_id, row.field_name)] = row
        return list(latest.values())
    except SQLAlchemyError as e:
        logger.error("get_slot_extractions_failed", error=str(e))
        return []


# ============ CONVERSATION HISTORY ============


async def get_conversation_history(db: AsyncSession, conversation_id: str) -> dict | None:
    """Return a conversation with its messages, tool executions, and slot extractions.

    Returns None when the conversation does not exist.
    """
    try:
        conv = await get_conversation(db, conversation_id)
        if conv is None:
            return None

        messages_result = await db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.asc())
        )
        messages = list(messages_result.scalars().all())

        tools_result = await db.execute(
            select(ToolExecution)
            .where(ToolExecution.conversation_id == conversation_id)
            .order_by(ToolExecution.executed_at.asc())
        )
        tool_executions = list(tools_result.scalars().all())

        slots_result = await db.execute(
            select(SlotExtraction)
            .where(SlotExtraction.conversation_id == conversation_id)
            .order_by(SlotExtraction.extracted_at.asc())
        )
        slot_extractions = list(slots_result.scalars().all())

        return {
            "conversation_id": conv.id,
            "agent_id": conv.agent_id,
            "agent_name": conv.agent_name,
            "started_at": conv.started_at.isoformat() if conv.started_at else None,
            "ended_at": conv.ended_at.isoformat() if conv.ended_at else None,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in messages
            ],
            "tool_executions": [
                {
                    "id": t.id,
                    "tool_id": t.tool_id,
                    "tool_type": t.tool_type,
                    "confirmed": t.confirmed,
                    "executed_at": t.executed_at.isoformat() if t.executed_at else None,
                    "result": t.result,
                }
                for t in tool_executions
            ],
            "slot_extractions": [
                {
                    "id": s.id,
                    "tool_id": s.tool_id,
                    "field_name": s.field_name,
                    "field_value": s.field_value,
                    "extracted_at": s.extracted_at.isoformat() if s.extracted_at else None,
                }
                for s in slot_extractions
            ],
        }
    except SQLAlchemyError as e:
        logger.error(
            "get_conversation_history_failed", conversation_id=conversation_id, error=str(e)
        )
        return None


# ============ TOOL EXECUTION CRUD ============


async def create_tool_execution(
    db: AsyncSession,
    conversation_id: str,
    tool_id: str,
    tool_type: str,
    result: dict | None = None,
) -> ToolExecution | None:
    """Record a tool invocation for the conversation history."""
    try:
        execution = ToolExecution(
            conversation_id=conversation_id,
            tool_id=tool_id,
            tool_type=tool_type,
            result=result,
        )
        db.add(execution)
        await db.commit()
        await db.refresh(execution)
        logger.info(
            "tool_execution_saved",
            conversation_id=conversation_id,
            tool_id=tool_id,
            tool_type=tool_type,
        )
        return execution
    except SQLAlchemyError as e:
        logger.error("create_tool_execution_failed", error=str(e))
        await db.rollback()
        return None


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


def _ensure_persona_constraints(config: dict) -> dict:
    """Return ``config`` with a sensible default ``persona_constraints`` when it
    has none, so a newly created user agent is never left unguarded (#168).

    A creator's own constraints (any of scope / out_of_scope / refusal_template
    populated) are left untouched; only a missing or fully-empty block is filled.
    Applied on the "Save as new" user-agent path only; the ``/v1/agent-configs``
    preset route stores an opaque FE blob verbatim (round-trip contract) and is
    left untouched.
    """
    existing = config.get("persona_constraints")
    if isinstance(existing, dict) and any(
        existing.get(k) for k in ("scope", "out_of_scope", "refusal_template")
    ):
        return config
    return {**config, "persona_constraints": default_persona_constraints().model_dump()}


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


# ============ USER AGENTS CRUD (stored in agent_configurations) ============


async def create_user_agents_from_templates(
    db: AsyncSession, user_id: int
) -> list[AgentConfiguration]:
    """Clone all active default templates into agent_configurations for a new user.

    The first template is marked is_default=True. Safe to call once per user
    on registration.
    """
    try:
        templates = await list_default_agent_templates(db, active_only=True)
        if not templates:
            logger.warning("create_user_agents_from_templates_no_templates", user_id=user_id)
            return []

        agents: list[AgentConfiguration] = []
        for i, tpl in enumerate(templates):
            agent = AgentConfiguration(
                id=uuid4().hex,
                user_id=user_id,
                template_id=tpl.id,
                name=tpl.name,
                config=tpl.config,
                is_default=(i == 0),
                is_customized=False,
            )
            db.add(agent)
            agents.append(agent)

        await db.commit()
        for agent in agents:
            await db.refresh(agent)

        logger.info("user_agents_created_from_templates", user_id=user_id, count=len(agents))
        return agents
    except SQLAlchemyError as e:
        logger.error("create_user_agents_from_templates_failed", user_id=user_id, error=str(e))
        await db.rollback()
        return []


async def create_user_agent(
    db: AsyncSession,
    user_id: int,
    name: str,
    config: dict,
) -> AgentConfiguration | None:
    """Create a brand-new user agent row, independent of any template.

    Used by the "Save as new" path so a fresh INSERT always happens — the
    caller's currently-loaded agent is never touched.
    """
    try:
        config = _ensure_persona_constraints(config)
        agent = AgentConfiguration(
            id=uuid4().hex,
            user_id=user_id,
            template_id=None,
            name=name,
            config=config,
            is_default=False,
            is_customized=True,
        )
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
        logger.info("user_agent_created", agent_id=agent.id, user_id=user_id)
        return agent
    except SQLAlchemyError as e:
        logger.error("create_user_agent_failed", user_id=user_id, error=str(e))
        await db.rollback()
        return None


async def list_user_agents(db: AsyncSession, user_id: int) -> list[AgentConfiguration]:
    try:
        result = await db.execute(
            select(AgentConfiguration)
            .where(AgentConfiguration.user_id == user_id)
            .order_by(AgentConfiguration.is_default.desc(), AgentConfiguration.created_at)
        )
        return list(result.scalars().all())
    except SQLAlchemyError as e:
        logger.error("list_user_agents_failed", user_id=user_id, error=str(e))
        return []


async def get_user_agent(
    db: AsyncSession, agent_id: str, user_id: int
) -> AgentConfiguration | None:
    try:
        result = await db.execute(
            select(AgentConfiguration).where(
                AgentConfiguration.id == agent_id,
                AgentConfiguration.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.error("get_user_agent_failed", agent_id=agent_id, error=str(e))
        return None


async def resolve_dependency_agent_config(
    db: AsyncSession, logical_id: str, user_id: int
) -> AgentConfig | None:
    """Resolve a workflow dependency id to a full AgentConfig.

    Workflow dependencies store logical ids (e.g. ``technical-support-agent-demo``),
    but saved rows in ``agent_configurations`` use a DB uuid primary key. Search
    user copies first, then admin/shared saves (``user_id IS NULL``).
    """
    row = await get_user_agent(db, logical_id, user_id)
    if row:
        return agent_config_from_stored_blob(row.config)

    try:
        matched = await _find_agent_config_by_logical_id(db, logical_id, user_id)
        if matched is None:
            return None
        return agent_config_from_stored_blob(matched.config or {})
    except SQLAlchemyError as e:
        logger.error(
            "resolve_dependency_agent_config_failed",
            logical_id=logical_id,
            user_id=user_id,
            error=str(e),
        )
        return None


async def enrich_request_dependency_configs(
    request: ConversationRequest,
    db: AsyncSession,
    user_id: int,
) -> ConversationRequest:
    """Attach resolved prerequisite AgentConfigs to a conversation request (transitive)."""
    from collections import deque

    from taskorbit.workflow_rules import collect_workflow_dependency_ids

    # Use a worklist to find all transitive dependencies
    all_dep_ids: set[str] = set()
    new_dep_configs: dict[str, AgentConfig] = {}

    # Start with the entry agent's dependencies
    to_check: deque[str] = deque(collect_workflow_dependency_ids(request.agent_config))

    logger.debug(
        "enrich_dependencies_start",
        entry_agent=request.agent_config.id,
        initial_to_check=to_check,
        user_id=user_id,
    )

    while to_check:
        dep_id = to_check.popleft()
        if dep_id in all_dep_ids:
            continue
        all_dep_ids.add(dep_id)

        # Check if already in request or new_dep_configs
        resolved = request.dependency_configs.get(dep_id) or new_dep_configs.get(dep_id)
        if not resolved:
            resolved = await resolve_dependency_agent_config(db, dep_id, user_id)
            if resolved:
                new_dep_configs[dep_id] = resolved
                logger.debug("enrich_dependency_resolved", id=dep_id, name=resolved.name)
            else:
                logger.warning(
                    "workflow_dependency_config_unresolved",
                    dependency=dep_id,
                    conversation_id=request.conversation_id,
                )

        # If we have a config, add its dependencies to the worklist
        if resolved:
            nested_deps = collect_workflow_dependency_ids(resolved)
            if nested_deps:
                logger.debug("enrich_dependency_nested_found", parent=dep_id, nested=nested_deps)
                to_check.extend(nested_deps)

    if not new_dep_configs:
        return request

    logger.info(
        "enrich_dependencies_complete",
        conversation_id=request.conversation_id,
        resolved_ids=list(new_dep_configs.keys()),
    )

    return request.model_copy(
        update={"dependency_configs": {**request.dependency_configs, **new_dep_configs}}
    )


async def update_user_agent(
    db: AsyncSession,
    agent_id: str,
    user_id: int,
    name: str | None = None,
    config: dict | None = None,
    is_default: bool | None = None,
) -> AgentConfiguration | None:
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
        agent.updated_at = datetime.now(UTC)
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
) -> AgentConfiguration | None:
    """Clone a default template into agent_configurations and apply updates.

    - If the user already has a copy of this template → update that copy.
    - If not → clone the template, mark is_customized=True, apply updates.
    - default_agent_templates is never modified.
    """
    try:
        result = await db.execute(
            select(AgentConfiguration).where(
                AgentConfiguration.user_id == user_id,
                AgentConfiguration.template_id == template_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            if name is not None:
                existing.name = name
            if config_updates is not None:
                existing.config = {**existing.config, **config_updates}
            existing.is_customized = True
            existing.updated_at = datetime.now()
            await db.commit()
            await db.refresh(existing)
            logger.info("user_agent_updated", agent_id=existing.id, user_id=user_id)
            return existing

        template = await get_default_agent_template(db, template_id)
        if not template:
            logger.warning("copy_on_write_template_not_found", template_id=template_id)
            return None

        agent = AgentConfiguration(
            id=uuid4().hex,
            user_id=user_id,
            template_id=template_id,
            name=name or template.name,
            config={**template.config, **(config_updates or {})},
            is_default=False,
            is_customized=True,
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


async def get_agent_configuration_by_id(
    db: AsyncSession, agent_id: str, user_id: int | None = None
) -> AgentConfiguration | None:
    """Look up a single AgentConfiguration by its primary key (async).

    When user_id is provided, only returns records owned by that user OR global
    template records (user_id IS NULL). Returns None for both missing rows and
    rows owned by another user — callers cannot distinguish the two cases.
    """
    try:
        query = select(AgentConfiguration).where(AgentConfiguration.id == agent_id)
        if user_id is not None:
            query = query.where(
                (AgentConfiguration.user_id == user_id) | (AgentConfiguration.user_id.is_(None))
            )
        result = await db.execute(query)
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.error("get_agent_configuration_by_id_failed", agent_id=agent_id, error=str(e))
        return None


async def get_agent_configuration_by_name(
    db: AsyncSession, name: str, user_id: int | None = None
) -> AgentConfiguration | None:
    """Look up a single AgentConfiguration by name, scoped to a user.

    When user_id is provided, matches records owned by that user only.
    When user_id is None (e.g. voice path before auth lands), fails closed:
    only global template records (user_id IS NULL) are returned so the voice
    path cannot resolve one user's custom agent into another user's session.
    """
    try:
        query = select(AgentConfiguration).where(AgentConfiguration.name == name)
        if user_id is not None:
            query = query.where(AgentConfiguration.user_id == user_id)
        else:
            # Fail-closed: unauthenticated callers see global templates only.
            query = query.where(AgentConfiguration.user_id.is_(None))
        result = await db.execute(query)
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.error(
            "get_agent_configuration_by_name_failed", name=name, user_id=user_id, error=str(e)
        )
        return None


async def list_user_agents_merged(db: AsyncSession, user_id: int) -> list[dict]:
    """Return all agents for a user — their customised copies AND all templates.

    Built-in templates always appear regardless of whether the user has a copy.
    Customised copies appear in addition, marked is_customized=True.
    The frontend uses is_customized to split the list into two sections.
    """
    user_agents = await list_user_agents(db, user_id)
    templates = await list_default_agent_templates(db, active_only=True)

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
                "is_customized": agent.is_customized,
                "created_at": agent.created_at,
                "updated_at": agent.updated_at,
            }
        )

    # All built-in templates — always included so the list never shrinks.
    for tpl in templates:
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


async def delete_conversation(db: AsyncSession, conversation_id: str) -> bool:
    """Delete a conversation and all its child records (messages, tool executions, slot extractions).

    Child rows are removed via SQLAlchemy cascade (all, delete-orphan) defined on the model.
    Returns True when a row was deleted, False when the ID doesn't exist.
    """
    result = await db.execute(delete(Conversation).where(Conversation.id == conversation_id))
    await db.commit()
    return result.rowcount > 0
