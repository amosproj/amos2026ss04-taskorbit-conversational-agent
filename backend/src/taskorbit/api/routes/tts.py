"""POST /v1/tts/synthesize — convert text to speech via ElevenLabs."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from taskorbit.config import get_settings
from taskorbit.logging.setup import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/tts", tags=["tts"])

_ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"


class TTSSynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


@router.post("/synthesize")
async def synthesize_speech(request: TTSSynthesizeRequest) -> StreamingResponse:
    """Stream MP3 audio for the given text from ElevenLabs.

    Returns a chunked audio/mpeg response the browser can play directly.
    """
    settings = get_settings()

    if not settings.elevenlabs_api_key:
        raise HTTPException(
            status_code=503, detail="ElevenLabs API key not configured."
        )

    url = _ELEVENLABS_URL.format(voice_id=settings.elevenlabs_voice_id)

    # The client is created outside the generator and closed in its finally
    # block so the connection stays open for the full streaming response.
    client = httpx.AsyncClient(timeout=30)

    async def _stream() -> AsyncIterator[bytes]:
        try:
            async with client.stream(
                "POST",
                url,
                headers={
                    "xi-api-key": settings.elevenlabs_api_key,
                    "Content-Type": "application/json",
                },
                json={"text": request.text, "model_id": settings.elevenlabs_model},
            ) as response:
                if not response.is_success:
                    logger.error(
                        "tts_elevenlabs_error",
                        status=response.status_code,
                        voice_id=settings.elevenlabs_voice_id,
                    )
                    return
                async for chunk in response.aiter_bytes():
                    yield chunk
        finally:
            await client.aclose()

    logger.info("tts_synthesize", text_length=len(request.text))
    return StreamingResponse(_stream(), media_type="audio/mpeg")
