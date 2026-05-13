"""Conversation routes - process, create, and retrieve conversations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from taskorbit.config import Settings, get_settings
from taskorbit.database import get_session
from taskorbit.database.crud import (
    create_conversation_message,
    get_messages_by_conversation,
)
from taskorbit.database.models import Conversation
from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import ConversationRequest, ConversationResponse, MessageRole

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


def get_orchestrator(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ConversationOrchestrator:
    return ConversationOrchestrator(settings=settings)


@router.post("/process", response_model=ConversationResponse)
async def process_conversation(
    request: ConversationRequest,
    orchestrator: ConversationOrchestrator = Depends(get_orchestrator),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
) -> ConversationResponse:
    """Process one turn of a conversation and persist messages."""
    try:
        response = await orchestrator.process_message(request)

        # Save user message
        last_user = next(
            (m for m in reversed(request.messages) if m.role == MessageRole.USER),
            None,
        )
        if last_user:
            create_conversation_message(
                db=db,
                conversation_id=request.conversation_id,
                role=last_user.role.value,
                content=last_user.content,
            )

        # Save assistant reply
        if response.reply:
            create_conversation_message(
                db=db,
                conversation_id=request.conversation_id,
                role=response.reply.role.value,
                content=response.reply.content,
            )

        logger.info("messages_persisted", conversation_id=request.conversation_id)
        return response

    except NotImplementedError as exc:
        raise HTTPException(
            status_code=501, detail="Orchestration engine not yet implemented."
        ) from exc


@router.post("", status_code=201)
def create_conversation(
    db: Session = Depends(get_session),  # noqa: B008
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
        db.commit()
        db.refresh(conversation)
        logger.info("conversation_created", conversation_id=conversation.id)
        return {"conversation_id": conversation.id, "started_at": str(conversation.started_at)}
    except Exception as e:
        db.rollback()
        logger.error("conversation_create_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create conversation") from e


@router.get("")
def get_conversations(
    db: Session = Depends(get_session),  # noqa: B008
) -> dict:
    """Get all conversations."""
    try:
        conversations = db.query(Conversation).order_by(Conversation.started_at.desc()).all()
        return {
            "conversations": [
                {
                    "conversation_id": c.id,
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
def get_conversation_messages(
    conversation_id: str,
    db: Session = Depends(get_session),  # noqa: B008
) -> dict:
    """Get all messages for a conversation."""
    try:
        messages = get_messages_by_conversation(db=db, conversation_id=conversation_id)
        if messages is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_messages_failed", error=str(e), conversation_id=conversation_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve messages") from e
