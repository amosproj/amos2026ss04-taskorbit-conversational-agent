"""POST /v1/conversations/process — main orchestration endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException  # noqa: F401

from taskorbit.config import Settings, get_settings
from taskorbit.logging.setup import get_logger
from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import ConversationRequest, ConversationResponse

log = get_logger(__name__)

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


def get_orchestrator(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ConversationOrchestrator:
    return ConversationOrchestrator(settings=settings)


@router.post("/process", response_model=ConversationResponse)
async def process_conversation(
    request: ConversationRequest,
    orchestrator: ConversationOrchestrator = Depends(get_orchestrator),  # noqa: B008
) -> ConversationResponse:
    """Process one turn of a conversation through the TaskOrbit orchestration engine."""
    log.info(
        "conversation_request_received",
        conversation_id=request.conversation_id,
        message_count=len(request.messages),
    )
    try:
        response = await orchestrator.process_message(request)
        log.info(
            "conversation_request_completed",
            conversation_id=request.conversation_id,
            intent=response.intent,
            status=response.status,
        )
        return response
    except NotImplementedError as exc:
        log.warning(
            "orchestration_not_implemented",
            conversation_id=request.conversation_id,
        )
        raise HTTPException(
            status_code=501, detail="Orchestration engine not yet implemented."
        ) from exc
