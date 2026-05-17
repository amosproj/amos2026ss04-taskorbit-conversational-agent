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

from livekit import rtc
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.agents.voice.room_io import RoomOutputOptions

from taskorbit.config import get_settings
from taskorbit.livekit_agent import build_agent_session, build_default_agent
from taskorbit.logging.setup import get_logger

logger = get_logger(__name__)

# Tunable: increase if the last word of an utterance is missing from replies.
_DEEPGRAM_FLUSH_DELAY_S: float = 0.3

# Explicit allowlist of data-channel message types this worker handles.
# Packets with any other `type` value are silently discarded.
_RECOGNISED_MSG_TYPES: frozenset[str] = frozenset({"commit_turn", "interrupt_playback"})


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    cfg = get_settings()
    session = build_agent_session(settings=cfg)
    agent = build_default_agent(settings=cfg)

    # Holds the most-recent pending reply task so it can be cancelled on
    # interruption before the orchestrator finishes processing.
    reply_task: asyncio.Task[None] | None = None

    async def _commit_and_reply() -> None:
        # Small delay so Deepgram can flush its final transcription segment
        # into the ChatContext before generate_reply() reads it. Without this,
        # the last word(s) of the utterance may be missing from the reply.
        try:
            await asyncio.sleep(_DEEPGRAM_FLUSH_DELAY_S)
            result = session.generate_reply()
            if asyncio.iscoroutine(result):
                await result
            logger.info("worker_generate_reply_triggered")
        except asyncio.CancelledError:
            # Interruption arrived before the orchestrator finished — discard
            # this turn cleanly so no stale reply reaches the user.
            logger.info("worker_generate_reply_cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("worker_generate_reply_failed", error=str(exc))

    # When the frontend Send button is clicked, useMicRecorder.sendUtterance()
    # publishes {"type": "commit_turn"} over the data channel. Handling it here
    # lets the agent start processing immediately instead of waiting for VAD
    # silence detection to time out.
    @ctx.room.on("data_received")
    def _on_data(packet: rtc.DataPacket) -> None:
        nonlocal reply_task
        if packet.participant is None:
            return
        if packet.participant.identity == ctx.room.local_participant.identity:
            return
        try:
            msg = json.loads(packet.data.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return
        msg_type = msg.get("type")
        if not isinstance(msg_type, str) or msg_type not in _RECOGNISED_MSG_TYPES:
            return
        if msg_type == "commit_turn":
            agent.request_reply()
            reply_task = asyncio.create_task(_commit_and_reply())
        elif msg_type == "interrupt_playback":
            if reply_task and not reply_task.done():
                reply_task.cancel()
                reply_task = None
            try:
                session.interrupt()
                logger.info("worker_interrupt_requested")
            except Exception as exc:  # noqa: BLE001
                logger.warning("worker_interrupt_failed", error=str(exc))

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
