"""POST /v1/tts/synthesize — convert text to speech via ElevenLabs."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from taskorbit.config import get_settings
from taskorbit.logging.setup import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/tts", tags=["tts"])

_ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


class TTSSynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    # When omitted, server defaults from environment (ELEVENLABS_*).
    voice_id: str | None = Field(default=None, max_length=128)
    model_id: str | None = Field(default=None, max_length=128)


@router.post("/synthesize")
async def synthesize_speech(request: TTSSynthesizeRequest) -> Response:
    """Return MP3 audio for the given text from ElevenLabs."""
    settings = get_settings()

    if not settings.elevenlabs_api_key:
        raise HTTPException(
            status_code=503, detail="ElevenLabs API key not configured."
        )

    url = _ELEVENLABS_URL.format(
        voice_id=request.voice_id or settings.elevenlabs_voice_id,
    )
    model = request.model_id or settings.elevenlabs_model

    async with httpx.AsyncClient(timeout=30) as client:
        el_response = await client.post(
            url,
            headers={
                "xi-api-key": settings.elevenlabs_api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": request.text,
                "model_id": model,
                "voice_settings": {
                    "stability": 0.75,
                    "similarity_boost": 0.75,
                    "style": 0.0,
                    "speed": 1.0,
                    "use_speaker_boost": True,
                },
            },
        )

    if not el_response.is_success:
        error_detail = el_response.text[:500]
        voice_used = request.voice_id or settings.elevenlabs_voice_id
        logger.error(
            "tts_elevenlabs_error",
            status=el_response.status_code,
            detail=error_detail,
            voice_id=voice_used,
        )
        raise HTTPException(
            status_code=502,
            detail=f"ElevenLabs error {el_response.status_code}: {error_detail}",
        )

    logger.info(
        "tts_synthesize_ok",
        text_length=len(request.text),
        audio_bytes=len(el_response.content),
    )
    return Response(content=el_response.content, media_type="audio/mpeg")
