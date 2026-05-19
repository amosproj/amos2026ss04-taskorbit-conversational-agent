"""Conversation routes - process, create, and retrieve conversations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from taskorbit.config import Settings, get_settings
from taskorbit.database import get_session
from taskorbit.database.crud import (
    create_conversation_message,
    get_messages_by_conversation,
)
from taskorbit.database.models import Conversation
from taskorbit.logging.setup import get_logger
from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import ConversationRequest, ConversationResponse, MessageRole

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


def get_orchestrator(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ConversationOrchestrator:
    return ConversationOrchestrator(settings=settings)


@router.post("/process", response_model=ConversationResponse)
async def process_conversation(
    request: ConversationRequest,
    orchestrator: ConversationOrchestrator = Depends(get_orchestrator),  # noqa: B008
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> ConversationResponse:
    """Process one turn of a conversation through the TaskOrbit orchestration engine and persist messages."""
    logger.info(
        "conversation_request_received",
        conversation_id=request.conversation_id,
        message_count=len(request.messages),
    )
    try:
        response = await orchestrator.process_message(request)

        # Save user message (only the last message if it's from user)
        last_msg = request.messages[-1] if request.messages else None
        last_user = last_msg if last_msg and last_msg.role == MessageRole.USER else None

        if last_user:
            result = await db.execute(
                select(Conversation).where(Conversation.id == request.conversation_id)
            )
            conversation = result.scalar_one_or_none()
            if not conversation:
                logger.warning("conversation_not_found", conversation_id=request.conversation_id)

            saved = await create_conversation_message(
                db=db,
                conversation_id=request.conversation_id,
                role=last_user.role.value,
                content=last_user.content,
            )
            if saved is None:
                logger.error("failed_to_save_user_message", conversation_id=request.conversation_id)

        # Save assistant reply
        if response.reply:
            saved = await create_conversation_message(
                db=db,
                conversation_id=request.conversation_id,
                role=response.reply.role.value,
                content=response.reply.content,
            )
            if saved is None:
                logger.error(
                    "failed_to_save_assistant_message", conversation_id=request.conversation_id
                )

        logger.info(
            "conversation_request_completed",
            conversation_id=request.conversation_id,
            intent=response.selected_intent,
            status=response.status,
        )
        return response

    except NotImplementedError as exc:
        logger.warning(
            "orchestration_not_implemented",
            conversation_id=request.conversation_id,
        )
        raise HTTPException(
            status_code=501, detail="Orchestration engine not yet implemented."
        ) from exc


@router.post("", status_code=201)
async def create_conversation(
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Create a new conversation."""
    conversation = Conversation(
        id=str(uuid.uuid4()),
        agent_id="default",
        agent_name="TaskOrbit",
        started_at=datetime.now(UTC),
    )
    try:
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        logger.info("conversation_created", conversation_id=conversation.id)
        return {"conversation_id": conversation.id, "started_at": str(conversation.started_at)}
    except Exception as e:
        await db.rollback()
        logger.error("conversation_create_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create conversation") from e


@router.get("")
async def get_conversations(
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Get all conversations."""
    try:
        result = await db.execute(select(Conversation).order_by(Conversation.started_at.desc()))
        conversations = result.scalars().all()
        return {
            "conversations": [
                {
                    "id": c.id,
                    "agent_name": c.agent_name,
                    "started_at": str(c.started_at),
                    "ended_at": str(c.ended_at) if c.ended_at else None,
                }
                for c in conversations
            ]
        }
    except Exception as e:
        logger.error("get_conversations_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve conversations") from e


@router.get("/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Get all messages for a conversation."""
    try:
        messages = await get_messages_by_conversation(db=db, conversation_id=conversation_id)
        return {
            "conversation_id": conversation_id,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "created_at": str(m.created_at),
                }
                for m in messages
            ],
        }
    except Exception as e:
        logger.error("get_messages_failed", error=str(e), conversation_id=conversation_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve messages") from e
