"""POST /v1/conversations/process — main orchestration endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException  # noqa: F401

from taskorbit.config import Settings, get_settings
from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import ConversationRequest, ConversationResponse

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
    try:
        return await orchestrator.process_message(request)
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=501, detail="Orchestration engine not yet implemented."
        ) from exc
