"""LiveKit agent building blocks (session + orchestrator bridge).

Voice runs on **LiveKit Cloud Agents** dispatched via
``POST /v1/livekit/token`` (``RoomAgentDispatch``). This package keeps the
``AgentSession`` factory and ``OrchestratorAgent`` adapter for tests and for
future self-hosted agent work — there is no longer an in-repo worker CLI.
"""

from __future__ import annotations

import uuid
from typing import Any

from livekit.agents.voice import AgentSession

from taskorbit.config import get_settings
from taskorbit.database import get_session
from taskorbit.livekit_agent.llm import OrchestratorAgent
from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import AgentConfig

__all__ = [
    "OrchestratorAgent",
    "build_agent_session",
    "build_default_agent",
]

# Global orchestrator instance (shared across sessions)
_orchestrator: ConversationOrchestrator | None = None


def _get_orchestrator() -> ConversationOrchestrator:
    """Get or create the shared ConversationOrchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        settings = get_settings()
        _orchestrator = ConversationOrchestrator(settings=settings)
    return _orchestrator


def _create_agent_config_from_metadata(metadata: dict[str, Any]) -> AgentConfig:
    """Extract agent configuration from LiveKit participant metadata."""
    from taskorbit.types import LLMConfig, STTConfig, TTSConfig
    
    return AgentConfig(
        id=metadata.get("agent_id", "livekit-default"),
        name=metadata.get("agent_name", "TaskOrbit"),
        persona=metadata.get("agent_persona", "A helpful voice assistant."),
        greeting=metadata.get("agent_greeting", "Hello! How can I help you?"),
        stt=STTConfig(
            provider=metadata.get("stt_provider", "deepgram"),
            model=metadata.get("stt_model", "nova-2"),
        ),
        llm=LLMConfig(
            provider=metadata.get("llm_provider", "openai"),
            model=metadata.get("llm_model", "gpt-4o-mini"),
        ),
        tts=TTSConfig(
            provider=metadata.get("tts_provider", "elevenlabs"),
            voice_id=metadata.get("tts_voice_id", "21m00Tcm4TlvDq8ikWAM"),
            model=metadata.get("tts_model", "eleven_monolingual_v1"),
        ),
        tools=[],
    )


def build_default_agent(settings: Any = None) -> OrchestratorAgent:
    """Build a default agent for testing without a database session."""
    orchestrator = _get_orchestrator()
    return OrchestratorAgent(
        orchestrator=orchestrator,
        conversation_id=str(uuid.uuid4()),
        db=None,
    )


async def build_agent_session(
    room_name: str = "",
    conversation_id: str | None = None,
    agent_config: AgentConfig | None = None,
    settings: Any = None,
) -> AgentSession:
    """Build an AgentSession for testing or worker use with database persistence."""
    if conversation_id is None:
        conversation_id = str(uuid.uuid4())
    
    if agent_config is None:
        agent_config = _create_agent_config_from_metadata({})
    
    # Get database session for persistence
    async for db in get_session():
        orchestrator = _get_orchestrator()
        agent = OrchestratorAgent(
            orchestrator=orchestrator,
            agent_config=agent_config,
            conversation_id=conversation_id,
            db=db,
        )
        session = AgentSession(agent=agent)
        return session
    
    raise RuntimeError("Could not create database session")