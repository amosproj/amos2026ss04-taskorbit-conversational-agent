"""Health endpoint.

The only route shipped with the dev-environment scaffold. Every other
route is the responsibility of downstream feature tickets.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from taskorbit import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe used by Docker, the frontend, and tests."""
    return HealthResponse(
        status="ok",
        service="taskorbit-backend",
        version=__version__,
    )
