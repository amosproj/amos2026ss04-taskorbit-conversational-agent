"""POST /v1/livekit/token — issue a signed LiveKit room access token.

Implements ticket #26 (LiveKit Cloud infrastructure) and aligns with
System Architecture #12: the backend mints short-lived JWTs that the
frontend uses to join LiveKit Cloud rooms for real-time audio.

The optional ``metadata`` field on the request is JSON-serialised and
attached to the participant via ``AccessToken.with_metadata``. The
local voice worker reads it as ``participant.metadata``; LiveKit Cloud
agents receive the same JSON on ``RoomAgentDispatch.metadata`` when
``LIVEKIT_AGENT_DISPATCH_NAME`` (or ``agent_dispatch_name`` on the
request) targets a cloud agent.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from livekit import api as lk_api

from taskorbit.config import get_settings
from taskorbit.logging.setup import get_logger
from taskorbit.types import LiveKitTokenRequest, LiveKitTokenResponse

router = APIRouter(prefix="/v1/livekit", tags=["livekit"])
log = get_logger(__name__)

# Hard cap on serialised participant metadata. LiveKit imposes a
# practical limit on JWT size; agent configs are small but tools could
# grow, so we fail fast rather than hand the user a confusing 401 from
# LiveKit later.
_MAX_METADATA_BYTES = 4096


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

    metadata_str: str | None = None
    if body.metadata is not None:
        metadata_str = json.dumps(body.metadata, separators=(",", ":"))
        if len(metadata_str.encode("utf-8")) > _MAX_METADATA_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"metadata exceeds {_MAX_METADATA_BYTES} bytes.",
            )

    dispatch_name = ""
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
        builder = (
            lk_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_identity(body.identity)
            .with_grants(grants)
        )
        if metadata_str is not None:
            builder = builder.with_metadata(metadata_str)

        dispatch_name = (body.agent_dispatch_name or "").strip() or (
            settings.livekit_agent_dispatch_name.strip() or settings.livekit_agent_name.strip()
        )
        if dispatch_name:
            # Room creation dispatch: Cloud / hosted agent joins when the user connects.
            # See https://docs.livekit.io/agents/server/agent-dispatch/
            dispatch_meta = metadata_str if metadata_str is not None else ""
            builder = builder.with_room_config(
                lk_api.RoomConfiguration(
                    agents=[
                        lk_api.RoomAgentDispatch(
                            agent_name=dispatch_name,
                            metadata=dispatch_meta,
                        )
                    ],
                ),
            )

        token = builder.to_jwt()
    except Exception as exc:  # pragma: no cover — defensive guard
        log.error("livekit_token_generation_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Token generation failed.") from exc

    log.info(
        "livekit_token_issued",
        identity=body.identity,
        room=body.room,
        has_metadata=metadata_str is not None,
        agent_dispatch=bool(dispatch_name),
    )
    return LiveKitTokenResponse(
        token=token,
        url=settings.livekit_url,
        room=body.room,
        identity=body.identity,
    )
