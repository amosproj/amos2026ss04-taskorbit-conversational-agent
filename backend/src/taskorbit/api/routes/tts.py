"""POST /v1/tts/synthesize — convert text to speech via ElevenLabs."""

from __future__ import annotations

import base64

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from taskorbit.config import get_settings
from taskorbit.logging.setup import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/tts", tags=["tts"])

_ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_ELEVENLABS_TIMESTAMPS_URL = (
    "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
)

_VOICE_SETTINGS = {
    "stability": 0.75,
    "similarity_boost": 0.75,
    "style": 0.0,
    "speed": 1.0,
    "use_speaker_boost": True,
}


class TTSSynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    # When omitted, server defaults from environment (ELEVENLABS_*).
    voice_id: str | None = Field(default=None, max_length=128)
    model_id: str | None = Field(default=None, max_length=128)


class WordTimestamp(BaseModel):
    word: str
    start_time: float
    end_time: float


class TTSWithTimestampsResponse(BaseModel):
    audio_base64: str
    word_timestamps: list[WordTimestamp]


def _chars_to_word_timestamps(
    characters: list[str],
    start_times: list[float],
    end_times: list[float],
) -> list[WordTimestamp]:
    """Convert ElevenLabs character-level alignment to word-level timestamps."""
    words: list[WordTimestamp] = []
    current_word = ""
    word_start = 0.0
    word_end = 0.0

    for char, start, end in zip(characters, start_times, end_times, strict=False):
        if char in (" ", "\n", "\t"):
            if current_word:
                words.append(WordTimestamp(word=current_word, start_time=word_start, end_time=word_end))
                current_word = ""
        else:
            if not current_word:
                word_start = start
            current_word += char
            word_end = end

    if current_word:
        words.append(WordTimestamp(word=current_word, start_time=word_start, end_time=word_end))

    return words


@router.post("/synthesize")
async def synthesize_speech(request: TTSSynthesizeRequest) -> Response:
    """Return MP3 audio for the given text from ElevenLabs."""
    settings = get_settings()

    if not settings.elevenlabs_api_key:
        raise HTTPException(status_code=503, detail="ElevenLabs API key not configured.")

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
                "voice_settings": _VOICE_SETTINGS,
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


@router.post("/synthesize-with-timestamps", response_model=TTSWithTimestampsResponse)
async def synthesize_with_timestamps(request: TTSSynthesizeRequest) -> TTSWithTimestampsResponse:
    """Return base64 MP3 + word-level timestamps from ElevenLabs.

    Uses the /with-timestamps endpoint which returns character-level alignment
    data. The response is converted to word-level timestamps so the frontend
    can reveal each word at the exact moment it is spoken.
    """
    settings = get_settings()

    if not settings.elevenlabs_api_key:
        raise HTTPException(status_code=503, detail="ElevenLabs API key not configured.")

    url = _ELEVENLABS_TIMESTAMPS_URL.format(
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
                "voice_settings": _VOICE_SETTINGS,
            },
        )

    if not el_response.is_success:
        error_detail = el_response.text[:500]
        logger.error(
            "tts_timestamps_elevenlabs_error",
            status=el_response.status_code,
            detail=error_detail,
        )
        raise HTTPException(
            status_code=502,
            detail=f"ElevenLabs error {el_response.status_code}: {error_detail}",
        )

    data = el_response.json()
    audio_base64: str = data.get("audio_base64", "")

    alignment = data.get("alignment") or {}
    characters: list[str] = alignment.get("characters", [])
    start_times: list[float] = alignment.get("character_start_times_seconds", [])
    end_times: list[float] = alignment.get("character_end_times_seconds", [])

    # ElevenLabs sometimes returns normalized_alignment with cleaner boundaries.
    norm = data.get("normalized_alignment") or {}
    if norm.get("characters"):
        characters = norm["characters"]
        start_times = norm.get("character_start_times_seconds", start_times)
        end_times = norm.get("character_end_times_seconds", end_times)

    word_timestamps = _chars_to_word_timestamps(characters, start_times, end_times)

    # Re-encode raw base64 string as proper base64 for the browser
    try:
        audio_bytes = base64.b64decode(audio_base64)
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    except Exception:
        audio_b64 = audio_base64

    logger.info(
        "tts_timestamps_ok",
        text_length=len(request.text),
        word_count=len(word_timestamps),
    )
    return TTSWithTimestampsResponse(audio_base64=audio_b64, word_timestamps=word_timestamps)
