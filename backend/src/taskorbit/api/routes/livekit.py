"""POST /v1/livekit/token — issue a signed LiveKit room access token."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from taskorbit.config import get_settings
from taskorbit.types import LiveKitTokenRequest, LiveKitTokenResponse

router = APIRouter(prefix="/v1/livekit", tags=["livekit"])


@router.post("/token", response_model=LiveKitTokenResponse)
async def create_livekit_token(body: LiveKitTokenRequest) -> LiveKitTokenResponse:
    """Return a signed JWT that grants the participant access to the named room.

    Requires LIVEKIT_API_KEY and LIVEKIT_API_SECRET to be set in the environment.
    """
    settings = get_settings()

    if not settings.livekit_api_key or not settings.livekit_api_secret:
        raise HTTPException(
            status_code=503,
            detail="LiveKit credentials not configured. Set LIVEKIT_API_KEY and LIVEKIT_API_SECRET.",
        )

    try:
        from livekit.api import AccessToken, VideoGrants  # type: ignore[import-untyped]

        token = (
            AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_grants(VideoGrants(room_join=True, room=body.room_name))
            .with_identity(body.participant_name)
            .to_jwt()
        )
        return LiveKitTokenResponse(token=token, url=settings.livekit_url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Token generation failed: {exc}") from exc
