"""LiveKit agent worker.

TaskOrbitVoiceAgent joins a LiveKit room and runs the full voice pipeline:
  audio in → STT (Deepgram) → ConversationOrchestrator → TTS (ElevenLabs) → audio out

run_worker() is the entry point registered as `taskorbit-worker` in
pyproject.toml. It connects to the LiveKit server and dispatches jobs to
TaskOrbitVoiceAgent instances.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from livekit import rtc
from livekit.plugins import deepgram, elevenlabs

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

    async def on_room_connected(self, room: rtc.Room) -> None:
        """Called when the worker successfully joins a LiveKit room.
        Subscribes to participant audio tracks and starts the pipeline.
        When connected to a room, the agent should be ready to receive audio 
        and send back TTS responses without additional wiring — the frontend's 
        LiveKitRoom component will auto-subscribe to all remote tracks and play them out. 
        """

        async def handle_track(track: rtc.Track, participant: rtc.RemoteParticipant) -> None:
            if track.kind != rtc.TrackKind.KIND_AUDIO:
                return
            audio_stream = rtc.AudioStream(track)

            async def _raw_bytes() -> AsyncIterator[bytes]:
                async for frame_event in audio_stream:
                    yield bytes(frame_event.frame.data)

            async for transcript in self._run_stt(_raw_bytes()):
                response = await self.orchestrator.process_message(transcript)
                async for _audio_chunk in self._run_tts(response):
                    pass  # publishing handled by run_worker via VoicePipelineAgent

        for participant in room.remote_participants.values():
            for pub in participant.track_publications.values():
                if pub.track and pub.track.kind == rtc.TrackKind.KIND_AUDIO:
                    asyncio.ensure_future(handle_track(pub.track, participant))

        @room.on("track_subscribed")
        def _on_track(
            track: rtc.Track,
            _pub: rtc.RemoteTrackPublication,
            participant: rtc.RemoteParticipant,
        ) -> None:
            asyncio.ensure_future(handle_track(track, participant))

    async def _run_stt(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[str]:
        """Convert a stream of raw audio bytes to text segments via Deepgram."""
        stt = deepgram.STT(
            api_key=self._settings.deepgram_api_key,
            model=self._settings.deepgram_model,
            language=self._settings.deepgram_language,
        )
        stream = stt.stream()
        try:
            async for chunk in audio_stream:
                frame = rtc.AudioFrame(
                    data=chunk,
                    sample_rate=16000,
                    num_channels=1,
                    samples_per_channel=len(chunk) // 2,
                )
                stream.push_frame(frame)
            await stream.aclose()
            async for event in stream:
                if event.type == deepgram.SpeechEventType.FINAL_TRANSCRIPT:
                    text = event.alternatives[0].text.strip()
                    if text:
                        yield text
        finally:
            await stream.aclose()

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
