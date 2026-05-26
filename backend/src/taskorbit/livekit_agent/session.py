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

import uuid
from typing import Any

from livekit.agents import AgentSession
from livekit.plugins import deepgram, elevenlabs, openai, silero
from livekit.plugins.elevenlabs import VoiceSettings

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
        vad=silero.VAD.load(
            activation_threshold=0.7,
            deactivation_threshold=0.45,
            min_speech_duration=0.2,
            min_silence_duration=0.55,
            prefix_padding_duration=0.4,
        ),
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
            encoding="mp3_44100_128",
            voice_settings=VoiceSettings(
                stability=0.75,
                similarity_boost=0.75,
                style=0.0,
                speed=1.0,
                use_speaker_boost=True,
            ),
        ),
        allow_interruptions=True,
        min_interruption_duration=0.8,
        turn_handling={
            "endpointing": {"mode": "manual"},
            "preemptive_generation": {"preemptive_tts": False},
        },
    )


def build_default_agent(
    *,
    orchestrator: ConversationOrchestrator | None = None,
    settings: Settings | None = None,
    db: Any = None,
    conversation_id: str | None = None,
) -> OrchestratorAgent:
    """Build the ``OrchestratorAgent`` paired with this session.

    Pass ``db`` and ``conversation_id`` from the worker entrypoint so the
    voice turn persists under the same conversation id the FE generated.
    Both fall back to safe defaults so existing test code keeps working.
    """
    return OrchestratorAgent(
        orchestrator=orchestrator or ConversationOrchestrator(settings=settings),
        conversation_id=conversation_id or str(uuid.uuid4()),
        db=db,
    )
