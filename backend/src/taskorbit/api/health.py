"""Health endpoint.

The only route shipped with the dev-environment scaffold. Every other
route is the responsibility of downstream feature tickets.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from taskorbit import __version__
from taskorbit.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    livekit_configured: bool


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe used by Docker, the frontend, and tests."""
    settings = get_settings()
    livekit_configured = bool(
        settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret
    )
    return HealthResponse(
        status="ok",
        service="taskorbit-backend",
        version=__version__,
        livekit_configured=livekit_configured,
    )
