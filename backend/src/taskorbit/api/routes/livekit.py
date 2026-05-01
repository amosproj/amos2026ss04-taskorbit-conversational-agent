"""POST /v1/livekit/token — issue a signed LiveKit room access token.

Implements ticket #26 (LiveKit Cloud infrastructure) and aligns with
System Architecture #12: the backend mints short-lived JWTs that the
frontend uses to join LiveKit Cloud rooms for real-time audio.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from livekit import api as lk_api  # type: ignore[import-untyped]

from taskorbit.config import get_settings
from taskorbit.logging.setup import get_logger
from taskorbit.types import LiveKitTokenRequest, LiveKitTokenResponse

router = APIRouter(prefix="/v1/livekit", tags=["livekit"])
log = get_logger(__name__)


@router.post("/token", response_model=LiveKitTokenResponse)
async def create_livekit_token(body: LiveKitTokenRequest) -> LiveKitTokenResponse:
    """Return a signed JWT that grants the participant access to the named room.

    Requires LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET to be set
    in the environment. Empty `identity` or `room` are rejected by Pydantic
    with a 422 before we get here.
    """
    settings = get_settings()
    if not (settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret):
        # Never echo which specific value is missing — keep the surface uniform.
        raise HTTPException(
            status_code=503,
            detail="LiveKit is not configured on this server.",
        )

    try:
        # `can_subscribe` already covers subscribing to data tracks in the
        # current livekit-api Python SDK — there is no separate
        # `can_subscribe_data` flag. The ticket's "if supported" wording
        # accounts for this.
        grants = lk_api.VideoGrants(
            room_join=True,
            room=body.room,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )
        token = (
            lk_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_identity(body.identity)
            .with_grants(grants)
            .to_jwt()
        )
    except Exception as exc:  # pragma: no cover — defensive guard
        log.error("livekit_token_generation_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Token generation failed.") from exc

    log.info("livekit_token_issued", identity=body.identity, room=body.room)
    return LiveKitTokenResponse(
        token=token,
        url=settings.livekit_url,
        room=body.room,
        identity=body.identity,
    )
