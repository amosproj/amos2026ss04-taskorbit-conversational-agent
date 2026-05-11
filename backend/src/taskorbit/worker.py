"""Local development worker — connects to LiveKit and runs the voice pipeline.

Run with:
    poetry run taskorbit-worker dev

The ``dev`` subcommand watches the LiveKit project for new rooms and
dispatches a session for each one. It also hot-reloads on code changes.

Required env vars (in backend/.env):
    LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
    DEEPGRAM_API_KEY
    ELEVENLABS_API_KEY
"""

from __future__ import annotations

import asyncio
import json
import logging

from livekit import rtc
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.agents.voice.room_io import RoomOutputOptions

from taskorbit.config import get_settings
from taskorbit.livekit_agent import build_agent_session, build_default_agent

logger = logging.getLogger(__name__)


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    cfg = get_settings()
    session = build_agent_session(settings=cfg)
    agent = build_default_agent(settings=cfg)

    # When the frontend Send button is clicked, useMicRecorder.sendUtterance()
    # publishes {"type": "commit_turn"} over the data channel. Handling it here
    # lets the agent start processing immediately instead of waiting for VAD
    # silence detection to time out.
    @ctx.room.on("data_received")
    def _on_data(packet: rtc.DataPacket) -> None:
        try:
            msg = json.loads(packet.data.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return
        if msg.get("type") == "commit_turn":
            try:
                agent.request_reply()
                result = session.generate_reply()
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
                logger.info("worker: generate_reply triggered")
            except Exception as exc:  # noqa: BLE001
                logger.warning("worker: generate_reply failed: %s", exc)

    # sync_transcription=False: publish agent transcript immediately instead of
    # timing it to audio playback, so text appears before/with audio in the UI.
    await session.start(
        agent,
        room=ctx.room,
        room_output_options=RoomOutputOptions(sync_transcription=False),
    )


def run_worker() -> None:
    cfg = get_settings()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            api_key=cfg.livekit_api_key,
            api_secret=cfg.livekit_api_secret,
            ws_url=cfg.livekit_url,
        )
    )
