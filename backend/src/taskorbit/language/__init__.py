"""Multilingual handling.

LanguageDetector identifies the language of user utterances so the
pipeline can select the right STT model, pass the correct language hint
to the LLM, and choose a matching TTS voice.

Initial scope: English ("en") and German ("de").
"""

from __future__ import annotations

from typing import ClassVar


class LanguageDetector:
    """Detects the BCP-47 language code of a text utterance."""

    SUPPORTED: ClassVar[set[str]] = {"en", "de"}
    FALLBACK: ClassVar[str] = "en"

    def detect(self, text: str) -> str:
        """Return a BCP-47 language code for the given text.

        Falls back to FALLBACK when detection is uncertain or the language
        is not in SUPPORTED.
        """
        raise NotImplementedError


def get_stt_language_code(config_language: str) -> str:
    """Map an AgentConfig stt_language value to the Deepgram language param.

    "multi" passes through as-is (Deepgram's automatic multi-language mode).
    Other values are validated against LanguageDetector.SUPPORTED.
    """
    raise NotImplementedError
