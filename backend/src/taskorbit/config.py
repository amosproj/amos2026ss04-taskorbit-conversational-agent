"""Centralised configuration.

All environment variables are loaded once, validated, and exposed as a
typed `Settings` object. Anywhere else in the codebase, import
`get_settings()` rather than reading os.environ directly — this keeps
configuration in a single place and makes testing easier (the cache can
be cleared between tests).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # --- CORS ---
    cors_allow_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Database ---
    # Declared so the database module can read it via `get_settings()`
    # without re-touching this file. The default points at the
    # docker-compose Postgres service.
    database_url: str = "postgresql://taskorbit:taskorbit@localhost:5432/taskorbit"

    # --- LiveKit ---
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # --- Deepgram (STT) ---
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    deepgram_language: str = "multi"

    # --- ElevenLabs (TTS) ---
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_model: str = "eleven_multilingual_v2"

    # --- LLM providers ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    google_api_key: str = ""
    google_model: str = "gemini-2.0-flash"

    @property
    def cors_origins_list(self) -> list[str]:
        """Comma-separated env var → list, with whitespace trimmed."""
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor.

    Use `get_settings.cache_clear()` in tests to force a re-read.
    """
    return Settings()
