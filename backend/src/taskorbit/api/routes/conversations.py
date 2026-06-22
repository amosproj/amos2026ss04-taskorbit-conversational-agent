"""Conversation routes - process, create, and retrieve conversations."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from taskorbit.api.deps import get_current_user_id
from taskorbit.config import Settings, get_settings
from taskorbit.database import get_session
from taskorbit.database.crud import (
    create_conversation,
    create_conversation_message,
    create_slot_extractions,
    create_tool_execution,
    enrich_request_dependency_configs,
    get_conversation,
    get_conversation_history,
    get_messages_by_conversation,
)
from taskorbit.database.models import Conversation  # used in POST "" route
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
    user_id: int = Depends(get_current_user_id),  # noqa: B008
) -> ConversationResponse:
    """Process one turn of a conversation through the TaskOrbit orchestration engine and persist messages."""
    # Auto-create conversation when absent or unknown so the frontend never
    # needs to call POST /v1/conversations explicitly before the first message.
    conversation_id = request.conversation_id
    if not conversation_id or not await get_conversation(db, conversation_id):
        conv = await create_conversation(
            db=db,
            agent_id=request.agent_config.id,
            agent_name=request.agent_config.name,
        )
        if conv is None:
            raise HTTPException(status_code=500, detail="Failed to create conversation")
        conversation_id = conv.id
        request = request.model_copy(update={"conversation_id": conversation_id})
        logger.info("conversation_auto_created", conversation_id=conversation_id)

    logger.info(
        "conversation_request_received",
        conversation_id=conversation_id,
        message_count=len(request.messages),
        llm_provider=request.agent_config.llm.provider,
        llm_model=request.agent_config.llm.model,
    )
    try:
        request = await enrich_request_dependency_configs(request, db, user_id)

        response = await orchestrator.process_message(request, db=db, user_id=user_id)

        # Save user message (last message in the list if sent by user)
        last_msg = request.messages[-1] if request.messages else None
        last_user = last_msg if last_msg and last_msg.role == MessageRole.USER else None

        if last_user:
            saved = await create_conversation_message(
                db=db,
                conversation_id=conversation_id,
                role=last_user.role.value,
                content=last_user.content,
                user_id=user_id,
            )
            if saved is None:
                logger.error("failed_to_save_user_message", conversation_id=conversation_id)

        # Save assistant reply
        if response.reply:
            saved = await create_conversation_message(
                db=db,
                conversation_id=conversation_id,
                role=response.reply.role.value,
                content=response.reply.content,
            )
            if saved is None:
                logger.error("failed_to_save_assistant_message", conversation_id=conversation_id)

        # Persist slot extractions with tool attribution for history transparency
        if response.extracted_slots:
            tool_id = response.tool_invoked.id if response.tool_invoked else "orchestrator"
            await create_slot_extractions(
                db=db,
                conversation_id=conversation_id,
                tool_id=tool_id,
                slots=response.extracted_slots,
                user_id=user_id,
            )

        # Record tool invocation so the history endpoint can surface it
        if response.tool_invoked:
            await create_tool_execution(
                db=db,
                conversation_id=conversation_id,
                tool_id=response.tool_invoked.id,
                tool_type=response.tool_invoked.type.value,
                result={"extracted_slots": response.extracted_slots}
                if response.extracted_slots
                else None,
            )

        logger.info(
            "conversation_request_completed",
            conversation_id=conversation_id,
            intent=response.selected_intent,
            status=response.status,
        )
        return response

    except NotImplementedError as exc:
        logger.warning(
            "orchestration_not_implemented",
            conversation_id=conversation_id,
        )
        raise HTTPException(
            status_code=501, detail="Orchestration engine not yet implemented."
        ) from exc


async def _sse_generator(
    http_request: Request,
    request: ConversationRequest,
    orchestrator: ConversationOrchestrator,
    db: AsyncSession,
    user_id: int,
):
    """Yield SSE-formatted events from process_message_stream.

    Event schema (agreed with frontend / Dev 2):
      data: {"type": "chunk", "text": "<token>"}
      data: {"type": "done", "intent": "...", "status": "...", "selected_agent": "...",
              "slots": {...}, "missing_slots": [...], "conversation_id": "...",
              "reply": "..." (when no chunks were streamed)}
      data: {"type": "error", "message": "..."}
    """
    # Persist user message upfront so it survives client disconnects.
    last_msg = request.messages[-1] if request.messages else None
    last_user = last_msg if last_msg and last_msg.role == MessageRole.USER else None
    if last_user:
        saved = await create_conversation_message(
            db=db,
            conversation_id=request.conversation_id,
            role=last_user.role.value,
            content=last_user.content,
            user_id=user_id,
        )
        if saved is None:
            logger.error(
                "sse_failed_to_save_user_message",
                conversation_id=request.conversation_id,
            )

    meta: ConversationResponse | None = None
    chunks_sent = 0

    async for event in orchestrator.process_message_stream(request, db=db, user_id=user_id):
        if await http_request.is_disconnected():
            logger.info("sse_client_disconnected", conversation_id=request.conversation_id)
            return

        if isinstance(event, str):
            chunks_sent += 1
            yield f"data: {json.dumps({'type': 'chunk', 'text': event})}\n\n"
        elif isinstance(event, ConversationResponse):
            meta = event

    if meta is None:
        return

    if meta.status == "error":
        yield f"data: {json.dumps({'type': 'error', 'message': meta.error or 'Unknown error'})}\n\n"
        return

    # Persist assistant reply after successful full stream
    if meta.reply:
        saved = await create_conversation_message(
            db=db,
            conversation_id=request.conversation_id,
            role=meta.reply.role.value,
            content=meta.reply.content,
        )
        if saved is None:
            logger.error(
                "sse_failed_to_save_assistant_message",
                conversation_id=request.conversation_id,
            )

        # Short-circuit paths (clarification, workflow confirmation, handoff-blocked,
        # manual transfer) put the reply only in meta.reply without yielding chunks.
        # Emit the text now so the frontend can render it.
        if chunks_sent == 0 and meta.reply.content:
            yield f"data: {json.dumps({'type': 'chunk', 'text': meta.reply.content})}\n\n"

    yield f"data: {json.dumps({'type': 'done', 'intent': meta.selected_intent, 'status': meta.status, 'selected_agent': meta.selected_agent, 'slots': meta.extracted_slots, 'missing_slots': meta.missing_slots, 'conversation_id': meta.conversation_id, 'locked_intent_name': meta.locked_intent_name, 'next_active_tool_id': meta.next_active_tool_id, 'tool_invoked': meta.tool_invoked.model_dump() if meta.tool_invoked else None, 'completed_workflow_steps': meta.completed_workflow_steps, 'confirmation': meta.confirmation.model_dump() if meta.confirmation else None})}\n\n"


@router.post("/stream")
async def stream_conversation(
    http_request: Request,
    request: ConversationRequest,
    orchestrator: ConversationOrchestrator = Depends(get_orchestrator),  # noqa: B008
    db: AsyncSession = Depends(get_session),  # noqa: B008
    user_id: int = Depends(get_current_user_id),  # noqa: B008
) -> StreamingResponse:
    """Stream one turn of a conversation token by token via Server-Sent Events.

    The client reads the event stream and renders tokens as they arrive.
    The final 'done' event carries intent, agent, and slot metadata.
    The user message is persisted upfront so it survives disconnects; the
    assistant reply is persisted after the full stream completes.
    """
    # Auto-create conversation when absent or unknown, mirroring /process.
    conversation_id = request.conversation_id
    if not conversation_id or not await get_conversation(db, conversation_id):
        conv = await create_conversation(
            db=db,
            agent_id=request.agent_config.id,
            agent_name=request.agent_config.name,
        )
        if conv is None:
            raise HTTPException(status_code=500, detail="Failed to create conversation")
        conversation_id = conv.id
        request = request.model_copy(update={"conversation_id": conversation_id})
        logger.info("conversation_auto_created", conversation_id=conversation_id)

    logger.info(
        "sse_stream_request_received",
        conversation_id=request.conversation_id,
        message_count=len(request.messages),
        llm_provider=request.agent_config.llm.provider,
        llm_model=request.agent_config.llm.model,
    )
    return StreamingResponse(
        _sse_generator(http_request, request, orchestrator, db, user_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("", status_code=201)
async def create_bare_conversation(
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


@router.get("/{conversation_id}/history")
async def get_history(
    conversation_id: str,
    db: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Return a conversation with all messages, tool executions, and slot extractions."""
    history = await get_conversation_history(db=db, conversation_id=conversation_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return history


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
