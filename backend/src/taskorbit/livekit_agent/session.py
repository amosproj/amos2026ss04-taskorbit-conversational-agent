"""Build an ``AgentSession`` wired with our STT, LLM-bridge, TTS, and VAD.

This factory exists so the worker entrypoint stays a thin wrapper and so
tests can assert the right component types are in place without
spinning up an actual LiveKit room.

The pipeline is:

    user audio  ─►  Silero VAD  ─►  Deepgram STT  ─►  OrchestratorAgent (llm_node)
                                                       │
                                                       ▼
    user audio out  ◄─  ElevenLabs TTS  ◄──────────  reply text

``allow_interruptions=True`` lets the user cut off agent TTS by speaking again
(barge-in) once echo cancellation has stabilised.
"""

from __future__ import annotations

from typing import Any

from livekit.agents import AgentSession
from livekit.plugins import deepgram, elevenlabs, openai, silero

from taskorbit.config import Settings, get_settings
from taskorbit.livekit_agent.llm import OrchestratorAgent
from taskorbit.orchestration import ConversationOrchestrator


def build_agent_session(
    *,
    settings: Settings | None = None,
) -> AgentSession[Any]:
    """Construct an ``AgentSession`` from the current settings.

    The orchestrator instance is owned by the returned session via the
    bound ``OrchestratorAgent`` — both share its lifetime. Caller is
    responsible for ``session.start(...)`` and ``session.aclose()``.
    """
    cfg = settings or get_settings()

    return AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(
            api_key=cfg.deepgram_api_key,
            model=cfg.deepgram_model,
            language=cfg.deepgram_language,
        ),
        # Required by generate_reply() — OrchestratorAgent.llm_node() overrides
        # this fully, so the OpenAI model is never actually called or billed.
        llm=openai.LLM(
            model=cfg.openai_model,
            api_key=cfg.openai_api_key or "sk-placeholder-not-used",
        ),
        tts=elevenlabs.TTS(
            api_key=cfg.elevenlabs_api_key,
            voice_id=cfg.elevenlabs_voice_id,
            model=cfg.elevenlabs_model,
        ),
        # Push-to-talk: only reply when generate_reply() is called explicitly.
        # "manual" endpointing disables VAD/silence auto-trigger.
        # preemptive_tts=False stops the session from calling llm_node early
        # to pre-warm TTS — that would fire the orchestrator before Send.
        turn_handling={
            "endpointing": {"mode": "manual"},
            "preemptive_generation": {"preemptive_tts": False},
        },
    )


def build_default_agent(
    *,
    orchestrator: ConversationOrchestrator | None = None,
    settings: Settings | None = None,
) -> OrchestratorAgent:
    """Build the ``OrchestratorAgent`` paired with this session.

    Kept separate from ``build_agent_session`` because ``session.start``
    expects the agent as a parameter, not as a constructor argument.
    """
    return OrchestratorAgent(
        orchestrator=orchestrator or ConversationOrchestrator(settings=settings),
    )
