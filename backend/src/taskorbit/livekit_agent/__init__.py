"""LiveKit agent worker.

TaskOrbitVoiceAgent joins a LiveKit room and runs the full voice pipeline:
  audio in → STT (Deepgram) → ConversationOrchestrator → TTS (ElevenLabs) → audio out

run_worker() is the entry point registered as `taskorbit-worker` in
pyproject.toml. It connects to the LiveKit server and dispatches jobs to
TaskOrbitVoiceAgent instances.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from livekit.plugins import elevenlabs

from taskorbit.config import Settings, get_settings
from taskorbit.orchestration import ConversationOrchestrator


class TaskOrbitVoiceAgent:
    """Runs the STT → orchestration → TTS pipeline inside a LiveKit room."""

    def __init__(
        self,
        orchestrator: ConversationOrchestrator,
        settings: Settings | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self._settings = settings or get_settings()

    async def on_room_connected(self, room: object) -> None:  # room: livekit.rtc.Room
        """Called when the worker successfully joins a LiveKit room.

        Subscribes to participant audio tracks and starts the pipeline.
        """
        raise NotImplementedError

    async def _run_stt(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[str]:
        """Convert a stream of raw audio bytes to text segments via Deepgram."""
        raise NotImplementedError
        yield ""

    async def _run_tts(self, text: str) -> AsyncIterator[bytes]:
        """Convert assistant text to audio bytes via ElevenLabs.

        Yields raw PCM audio chunks as they stream back from ElevenLabs.
        The caller is responsible for forwarding chunks to the LiveKit room.
        """
        tts = elevenlabs.TTS(
            voice_id=self._settings.elevenlabs_voice_id,
            model=self._settings.elevenlabs_model,
            api_key=self._settings.elevenlabs_api_key,
        )
        try:
            async with tts.synthesize(text) as stream:
                async for audio in stream:
                    yield bytes(audio.frame.data)
        finally:
            await tts.aclose()


def run_worker() -> None:
    """Entry point for `poetry run taskorbit-worker`.

    Connects to the LiveKit server using credentials from settings and
    starts accepting agent dispatch jobs.
    """
    raise NotImplementedError
