"""Build an ``AgentSession`` wired with our STT, LLM-bridge, TTS, and VAD.

This factory exists so the worker entrypoint stays a thin wrapper and so
tests can assert the right component types are in place without
spinning up an actual LiveKit room.

The pipeline is:

    user audio  ─►  Silero VAD  ─►  STT  ─►  OrchestratorAgent (llm_node)
                                               │
                                               ▼
    user audio out  ◄─────  TTS  ◄──────────  reply text

STT and TTS providers are selected per-agent from ``agent_config`` (#135):
either stage can use Deepgram or ElevenLabs independently. When no config
is present the historical defaults apply (Deepgram STT, ElevenLabs TTS).

``allow_interruptions=True`` lets the user cut off agent TTS by speaking again
(barge-in) once echo cancellation has stabilised.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from livekit.agents import AgentSession
from livekit.plugins import deepgram, elevenlabs, openai, silero
from livekit.plugins.elevenlabs import VoiceSettings

from taskorbit.config import Settings, get_settings
from taskorbit.livekit_agent.llm import OrchestratorAgent
from taskorbit.logging.setup import get_logger
from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import AgentConfig, STTProvider, TTSProvider

logger = get_logger(__name__)

# Provider-native model defaults used when the configured model string does
# not belong to the selected provider (e.g. a saved config carries a Deepgram
# model name but the user switched the provider to ElevenLabs). Prevents a
# cross-provider model name from crashing the voice pipeline at runtime.
#
# "scribe_v2_realtime" is pinned deliberately: the plugin's own default
# resolves to BATCH scribe_v1 (streaming=False), whose final transcripts
# arrive only after a full HTTP round trip, too late for the worker's
# manual endpointing + flush-delay turn handling. The realtime model keeps
# streaming parity with Deepgram's semantics.
_ELEVENLABS_STT_DEFAULT_MODEL = "scribe_v2_realtime"
_DEEPGRAM_TTS_DEFAULT_MODEL = "aura-2-andromeda-en"


# Per-provider "does this model belong to me?" predicates. Keeping all four in
# one place (rather than a different ad-hoc check inside each build branch) is
# what makes cross-provider detection symmetric: every branch routes its model
# choice through ``_resolve_model`` with one of these.
def _is_deepgram_stt_model(model: str) -> bool:
    # Deepgram STT models are the Nova family (nova-3 is the FE default).
    # The trailing hyphen also rejects typos like "nova3" that the API
    # would reject mid-call.
    return model.startswith("nova-")


def _is_elevenlabs_stt_model(model: str) -> bool:
    # Only the realtime Scribe model streams; the batch models (scribe_v1,
    # scribe_v2) arrive too late for the worker's manual endpointing.
    return model == _ELEVENLABS_STT_DEFAULT_MODEL


def _is_deepgram_tts_model(model: str) -> bool:
    # Aura voices encode the voice in the model name (aura-2-<voice>-en).
    return model.startswith("aura")


def _is_elevenlabs_tts_model(model: str) -> bool:
    return model.startswith("eleven_")


def _resolve_model(
    *,
    stage: str,
    provider: str,
    configured: str | None,
    is_valid: Callable[[str], bool],
    fallback: str,
) -> str:
    """Return ``configured`` if it is valid for ``provider``, else ``fallback``.

    Single source of truth for cross-provider model detection so all four
    STT/TTS branches behave identically: a model string that does not belong
    to the selected provider is replaced with that provider's safe default and
    a single ``model_not_valid_for_provider`` warning is logged. That warning
    is the only production signal that an agent was misconfigured, so it must
    fire on every mismatch (covered by tests).
    """
    if configured and is_valid(configured):
        return configured
    if configured:
        logger.warning(
            "model_not_valid_for_provider",
            stage=stage,
            provider=provider,
            configured_model=configured,
            fallback_model=fallback,
        )
    return fallback


def _build_stt(cfg: Settings, agent_config: AgentConfig | None) -> deepgram.STT | elevenlabs.STT:
    """Construct the STT plugin selected by ``agent_config.stt.provider`` (#135).

    Defaults to Deepgram (historical behavior) when no config is present.
    """
    stt_cfg = agent_config.stt if agent_config is not None else None

    if stt_cfg is not None and stt_cfg.provider == STTProvider.ELEVENLABS:
        model_id = _resolve_model(
            stage="stt",
            provider="elevenlabs",
            configured=stt_cfg.model,
            is_valid=_is_elevenlabs_stt_model,
            fallback=_ELEVENLABS_STT_DEFAULT_MODEL,
        )
        logger.info("stt_selected", provider="elevenlabs", model=model_id)
        return elevenlabs.STT(
            api_key=cfg.elevenlabs_api_key,
            model_id=model_id,
        )

    model = _resolve_model(
        stage="stt",
        provider="deepgram",
        configured=stt_cfg.model if stt_cfg is not None else None,
        is_valid=_is_deepgram_stt_model,
        fallback=cfg.deepgram_model,
    )
    logger.info("stt_selected", provider="deepgram", model=model)
    return deepgram.STT(
        api_key=cfg.deepgram_api_key,
        model=model,
        language=cfg.deepgram_language,
        smart_format=True,
        numerals=True,
        endpointing_ms=400,
    )


def _build_tts(cfg: Settings, agent_config: AgentConfig | None) -> deepgram.TTS | elevenlabs.TTS:
    """Construct the TTS plugin selected by ``agent_config.tts.provider`` (#135).

    Defaults to ElevenLabs (historical behavior) when no config is present.
    The agent config's ``voice_id`` takes precedence over the environment's
    ``ELEVENLABS_VOICE_ID``. Previously env always won, which made the
    config field a non-functional placeholder.
    """
    tts_cfg = agent_config.tts if agent_config is not None else None

    if tts_cfg is not None and tts_cfg.provider == TTSProvider.DEEPGRAM:
        # Aura voices are encoded in the model name; voice_id is unused here.
        model = _resolve_model(
            stage="tts",
            provider="deepgram",
            configured=tts_cfg.model,
            is_valid=_is_deepgram_tts_model,
            fallback=_DEEPGRAM_TTS_DEFAULT_MODEL,
        )
        logger.info("tts_selected", provider="deepgram", model=model)
        return deepgram.TTS(
            api_key=cfg.deepgram_api_key,
            model=model,
            # Pin the plugin defaults explicitly so an upgrade cannot
            # silently change the audio characteristics.
            encoding="linear16",
            sample_rate=24000,
        )

    voice_id = cfg.elevenlabs_voice_id
    voice_source = "env"
    if tts_cfg is not None and tts_cfg.voice_id:
        voice_id = tts_cfg.voice_id
        voice_source = "config"
    model = _resolve_model(
        stage="tts",
        provider="elevenlabs",
        configured=tts_cfg.model if tts_cfg is not None else None,
        is_valid=_is_elevenlabs_tts_model,
        fallback=cfg.elevenlabs_model,
    )
    logger.info(
        "tts_selected",
        provider="elevenlabs",
        model=model,
        voice_id=voice_id,
        voice_source=voice_source,
    )
    return elevenlabs.TTS(
        api_key=cfg.elevenlabs_api_key,
        voice_id=voice_id,
        model=model,
        # Plugin default is mp3_22050_32 (22 kHz / 32 kbps) which sounds
        # noticeably different from the REST endpoint used for the greeting
        # (which returns mp3_44100_128 by default). Match that quality here
        # so both paths use the same audio characteristics.
        encoding="mp3_44100_128",
        voice_settings=VoiceSettings(
            stability=0.75,
            similarity_boost=0.75,
            style=0.0,
            speed=1.0,
            use_speaker_boost=True,
        ),
    )


def build_agent_session(
    *,
    settings: Settings | None = None,
    agent_config: AgentConfig | None = None,
) -> AgentSession[Any]:
    """Construct an ``AgentSession`` from the current settings.

    Pass ``agent_config`` (parsed from participant metadata) so the STT and
    TTS providers the user selected in the agent configuration are the ones
    actually constructed (#135). Without it, historical defaults apply.

    The orchestrator instance is owned by the returned session via the
    bound ``OrchestratorAgent`` — both share its lifetime. Caller is
    responsible for ``session.start(...)`` and ``session.aclose()``.
    """
    cfg = settings or get_settings()

    stt = _build_stt(cfg, agent_config)
    tts = _build_tts(cfg, agent_config)

    return AgentSession(
        vad=silero.VAD.load(
            activation_threshold=0.7,
            deactivation_threshold=0.45,
            min_speech_duration=0.2,
            min_silence_duration=1.5,
            prefix_padding_duration=0.4,
        ),
        stt=stt,
        # Required by generate_reply() — OrchestratorAgent.llm_node() overrides
        # this fully, so the OpenAI model is never actually called or billed.
        llm=openai.LLM(
            model=cfg.openai_model,
            api_key=cfg.openai_api_key or "sk-placeholder-not-used",
        ),
        tts=tts,
        # Barge-in: stop agent TTS as soon as the user sustains speech for
        # min_interruption_duration seconds. Brief noises (clicks, coughs)
        # shorter than the threshold do not trigger an interruption.
        allow_interruptions=True,
        min_interruption_duration=0.8,
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
    agent_config: AgentConfig | None = None,
    conversation_id: str | None = None,
) -> OrchestratorAgent:
    """Build the ``OrchestratorAgent`` paired with this session.

    Kept separate from ``build_agent_session`` because ``session.start``
    expects the agent as a parameter, not as a constructor argument.

    Pass ``agent_config`` when the caller has parsed it from participant
    metadata (#100) so the voice path uses the user's saved configuration
    instead of the hardcoded ``_default_agent_config`` fallback. With the
    full agent (including tools) the orchestrator can also dispatch the
    agent_transfer tool on voice, enabling mid-call handoff (AC7 of #8).

    Pass ``conversation_id`` (= LiveKit room name) so voice turns are
    persisted under the same conversation ID the frontend tracks.
    """
    kwargs: dict = dict(
        orchestrator=orchestrator or ConversationOrchestrator(settings=settings),
        agent_config=agent_config,
    )
    if conversation_id is not None:
        kwargs["conversation_id"] = conversation_id
    return OrchestratorAgent(**kwargs)
