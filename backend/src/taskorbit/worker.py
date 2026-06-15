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
from pydantic import ValidationError

from taskorbit.config import get_settings
from taskorbit.livekit_agent import build_agent_session, build_default_agent
from taskorbit.logging.setup import get_logger
from taskorbit.observability.metrics import configure_default_metrics, get_metrics
from taskorbit.types import AgentConfig

logger = get_logger(__name__)

# Tunable: increase if the last word of an utterance is missing from replies.
_DEEPGRAM_FLUSH_DELAY_S: float = 0.3

# Explicit allowlist of data-channel message types this worker handles.
# Packets with any other `type` value are silently discarded.
_RECOGNISED_MSG_TYPES: frozenset[str] = frozenset({"commit_turn", "interrupt_playback"})

# Topic the FE subscribes to via useAgentHandoff to swap the active agent
# card mid-call without dropping the LiveKit room. #8 Task 6 AC7.
_HANDOFF_TOPIC: str = "taskorbit.agent_handoff"
_ROUTED_AGENT_TOPIC: str = "taskorbit.agent_routed"


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    cfg = get_settings()

    # Read participant metadata and parse it into an AgentConfig so the
    # voice path uses the user's saved configuration instead of the
    # hardcoded fallback in ``_default_agent_config`` (#100). The frontend
    # serialises this via ``buildLiveKitWorkerMetadata`` and the backend
    # embeds it in ``RoomAgentDispatch.metadata`` on the JWT. Carrying the
    # full agent (including tools) is what enables voice-side agent_transfer
    # dispatch for the mid-call handoff (AC7 of #8).
    #
    # ``greeting`` is still extracted separately because ``session.say()``
    # below speaks it through the same TTS/WebRTC pipeline as every other
    # agent turn; the frontend used to call ElevenLabs directly which
    # produced a different audio path (plain MP3 vs WebRTC Opus).
    greeting: str = ""
    agent_config: AgentConfig | None = None
    try:
        participant = await asyncio.wait_for(ctx.wait_for_participant(), timeout=30.0)
        meta = json.loads(participant.metadata or "{}")
        greeting = str(meta.get("greeting") or "")
        try:
            agent_config = AgentConfig.model_validate(meta)
            logger.info(
                "worker_agent_config_loaded_from_metadata",
                agent_id=agent_config.id,
                agent_name=agent_config.name,
            )
        except ValidationError as exc:
            logger.warning(
                "worker_agent_config_parse_failed",
                error=str(exc),
                fallback="_default_agent_config",
            )
    except Exception:  # noqa: BLE001
        pass

    session = build_agent_session(settings=cfg)
    agent = build_default_agent(settings=cfg, agent_config=agent_config)

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

    # Holds the most-recent pending reply task so it can be cancelled on
    # interruption before the orchestrator finishes processing.
    reply_task: asyncio.Task[None] | None = None

    async def _commit_and_reply(turn_start: float) -> None:
        # Small delay so Deepgram can flush its final transcription segment
        # into the ChatContext before generate_reply() reads it. Without this,
        # the last word(s) of the utterance may be missing from the reply.
        try:
            await asyncio.sleep(_DEEPGRAM_FLUSH_DELAY_S)
            # generate_reply() returns a SpeechHandle synchronously; the actual
            # llm_node + orchestrator work happens in the background. We must
            # wait_for_playout() so the orchestrator finishes stashing the
            # pending handoff target before we read it below — otherwise the
            # publish fires before the stash, and the handoff is silently lost.
            handle = session.generate_reply()
            if asyncio.iscoroutine(handle):
                handle = await handle
            try:
                await handle.wait_for_playout()
            except Exception:  # noqa: BLE001
                pass
            _turn_elapsed = time.perf_counter() - turn_start
            get_metrics().pipeline_latency_seconds.labels(stage="worker_turn").observe(
                _turn_elapsed
            )
            logger.info("voice_turn_complete", latency_ms=round(_turn_elapsed * 1000, 1))
            logger.info(
                "worker_generate_reply_triggered",
                turn_latency_ms=round(_turn_elapsed * 1000, 1),
            )

            # Publish the routed agent name after each turn so the frontend
            # can display which specialist is currently handling the call.
            if agent._current_routed_agent:
                try:
                    payload = json.dumps(
                        {"type": "agent_routed", "agent": agent._current_routed_agent}
                    )
                    await ctx.room.local_participant.publish_data(
                        payload, reliable=True, topic=_ROUTED_AGENT_TOPIC
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("worker_agent_routed_publish_failed", error=str(exc))

            # AC7: now that the orchestrator has finished (wait_for_playout
            # above), the pending target is set if an agent_transfer dispatched
            # this turn. Publish on the FE-subscribed topic so the client
            # swaps the active agent card without dropping the LiveKit room.
            pending = agent._pending_handoff_target
            if pending:
                try:
                    payload = json.dumps({"type": "agent_handoff", "target": pending})
                    await ctx.room.local_participant.publish_data(
                        payload, reliable=True, topic=_HANDOFF_TOPIC
                    )
                    logger.info("worker_handoff_published", target=pending, topic=_HANDOFF_TOPIC)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("worker_handoff_publish_failed", error=str(exc))
                finally:
                    agent._pending_handoff_target = None
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
            t_now = time.perf_counter()
            if reply_task and not reply_task.done():
                reply_task.cancel()
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


def run_worker() -> None:
    import os

    # prometheus_client multiprocess mode: when PROMETHEUS_MULTIPROC_DIR is set,
    # each LiveKit subprocess writes metrics to files in that directory.
    # MultiProcessCollector aggregates them so the HTTP server reflects all processes.
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
