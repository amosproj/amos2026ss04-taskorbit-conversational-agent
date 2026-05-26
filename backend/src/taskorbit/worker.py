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
import time

from livekit import rtc
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.agents.metrics import STTMetrics, TTSMetrics
from livekit.agents.voice.events import AgentEvent

from taskorbit.config import get_settings
from taskorbit.database import AsyncSessionLocal
from taskorbit.livekit_agent import build_agent_session, build_default_agent
from taskorbit.logging.setup import get_logger
from taskorbit.observability.metrics import configure_default_metrics, get_metrics

logger = get_logger(__name__)

_DEEPGRAM_FLUSH_DELAY_S: float = 0.3
_RECOGNISED_MSG_TYPES: frozenset[str] = frozenset({"commit_turn", "interrupt_playback"})


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    cfg = get_settings()

    greeting: str = ""
    conversation_id: str | None = None
    meta: dict = {}
    try:
        participant = await ctx.wait_for_participant()
        meta = json.loads(participant.metadata or "{}")
        greeting = str(meta.get("greeting") or "")
        conversation_id = meta.get("conversation_id") or None
    except Exception:  # noqa: BLE001
        pass

    logger.info(
        "worker_entrypoint_started",
        has_conversation_id=conversation_id is not None,
        conversation_id=conversation_id or "none",
    )

    session = build_agent_session(settings=cfg)

    db_session = AsyncSessionLocal()
    agent = build_default_agent(
        settings=cfg,
        db=db_session,
        conversation_id=conversation_id,
    )

    @session.on("metrics_collected")
    def _on_metrics(ev: AgentEvent) -> None:
        m = getattr(ev, "metrics", None)
        if isinstance(m, TTSMetrics):
            get_metrics().pipeline_latency_seconds.labels(stage="tts_ttfb").observe(m.ttfb)
            get_metrics().pipeline_latency_seconds.labels(stage="tts_synthesis").observe(m.duration)
            get_metrics().voice_pipeline_requests_total.labels(
                handler="/v1/tts/synthesize", status="success"
            ).inc()
            logger.debug(
                "tts_metrics_collected",
                ttfb_ms=round(m.ttfb * 1000, 1),
                duration_ms=round(m.duration * 1000, 1),
                audio_duration_ms=round(m.audio_duration * 1000, 1),
                cancelled=m.cancelled,
            )
        elif isinstance(m, STTMetrics):
            if m.duration > 0:
                get_metrics().pipeline_latency_seconds.labels(stage="stt_processing").observe(
                    m.duration
                )
            logger.debug(
                "stt_metrics_collected",
                duration_ms=round(m.duration * 1000, 1),
                audio_duration_ms=round(m.audio_duration * 1000, 1),
            )

    reply_task: asyncio.Task[None] | None = None

    async def _commit_and_reply(turn_start: float) -> None:
        try:
            await asyncio.sleep(_DEEPGRAM_FLUSH_DELAY_S)
            result = session.generate_reply()
            if asyncio.iscoroutine(result):
                await result
            _turn_elapsed = time.perf_counter() - turn_start
            get_metrics().pipeline_latency_seconds.labels(stage="worker_turn").observe(
                _turn_elapsed
            )
            logger.info(
                "worker_generate_reply_triggered",
                turn_latency_ms=round(_turn_elapsed * 1000, 1),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("worker_generate_reply_failed", error=str(exc))

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
            t_now = time.perf_counter()
            agent.request_reply(t_commit=t_now)
            reply_task = asyncio.create_task(_commit_and_reply(t_now))
        elif msg_type == "interrupt_playback":
            if reply_task and not reply_task.done():
                reply_task.cancel()
                reply_task = None
            try:
                session.interrupt()
                logger.info("worker_interrupt_requested")
            except Exception as exc:  # noqa: BLE001
                logger.warning("worker_interrupt_failed", error=str(exc))

    await session.start(agent, room=ctx.room)

    if greeting:
        session.say(greeting)
        logger.info("worker_greeting_spoken", length=len(greeting))

    await db_session.aclose()
    logger.info("worker_db_session_closed", conversation_id=conversation_id or "none")


def run_worker() -> None:
    import os

    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if multiproc_dir:
        os.makedirs(multiproc_dir, exist_ok=True)

    configure_default_metrics()

    from prometheus_client import CollectorRegistry, start_http_server

    if multiproc_dir:
        from prometheus_client.multiprocess import MultiProcessCollector

        registry = CollectorRegistry()
        MultiProcessCollector(registry)
        start_http_server(port=8001, registry=registry)
    else:
        start_http_server(port=8001)

    logger.info("worker_metrics_server_started", port=8001)
    cfg = get_settings()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            api_key=cfg.livekit_api_key,
            api_secret=cfg.livekit_api_secret,
            ws_url=cfg.livekit_url,
        )
    )
