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
from livekit.plugins import deepgram, elevenlabs, silero

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
        tts=elevenlabs.TTS(
            api_key=cfg.elevenlabs_api_key,
            voice_id=cfg.elevenlabs_voice_id,
            model=cfg.elevenlabs_model,
        ),
        # User can cut off TTS by speaking again once echo cancellation is warm.
        allow_interruptions=True,
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
