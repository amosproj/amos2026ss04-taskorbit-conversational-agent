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

    The STT and TTS plugins are built here, so the per-agent selections
    parsed from participant metadata (#87 — STT model, TTS voice + model)
    must be threaded in or the user's dropdown choices never reach the
    audio path and the env defaults are used regardless. When
    ``agent_config`` is absent or a field is empty the env defaults apply
    (legacy / fallback, AC5). The LLM model is intentionally NOT taken from
    here: ``OrchestratorAgent.llm_node`` overrides the bridge LLM and calls
    the model named in ``agent_config.llm.model`` itself.
    """
    cfg = settings or get_settings()

    stt = _build_stt(cfg, agent_config)
    tts = _build_tts(cfg, agent_config)

    return AgentSession(
        vad=silero.VAD.load(
            activation_threshold=0.7,
            # Raised 0.45 -> 0.6 (#153): a steady fan parks Silero's speech
            # probability in the 0.45-0.7 hysteresis band, holding the turn open
            # so end-of-speech never fires. A higher deactivation threshold lets
            # the turn end when the user stops even with background noise. Tune
            # down if it clips quiet pauses in real speech.
            deactivation_threshold=0.6,
            min_speech_duration=0.2,
            # Held at 1.5s by the #102 regression guard: a shorter window lets a
            # mid-sentence pause end the turn early and split one utterance into
            # multiple transcript bubbles. This is also the trade-off behind the
            # brief "still listening" lag after the user stops; shortening it
            # safely needs a grammar-aware endpoint, not just a smaller timer.
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
        # Server-side VAD turn detection (turn_detection="vad"): Silero detects
        # when the user stops speaking and the framework commits the turn. This
        # is more noise-robust than the browser's amplitude check (#153).
        #
        # preemptive_generation is DISABLED (enabled=False). Its default is
        # enabled=True, and preemptive_tts=False only suppresses early TTS
        # synthesis -- it does NOT stop the framework from invoking llm_node
        # early on a partial / pre-flush transcript. Disabling it removes that
        # extra concurrent llm_node call so the worker's commit-driven reply,
        # which reads the live finalized transcript, is the single reply path
        # and cannot be beaten to the gate by a pre-flush snapshot (#153).
        #
        # Interruption is left at the LiveKit 1.6.0 defaults (min_duration=0.5,
        # resume_false_interruption=True). A more aggressive override
        # (min_duration=0.2 + resume_false_interruption=False) was tried for
        # snappier barge-in but it tripped on ambient noise / echo mid-reply and
        # cancelled the agent's own answers, so it is reverted. Tuning barge-in
        # safely needs the echo path sorted first (headphones / proper AEC).
        turn_handling={
            "turn_detection": "vad",
            "preemptive_generation": {"enabled": False},
        },
    )


def build_default_agent(
    *,
    orchestrator: ConversationOrchestrator | None = None,
    settings: Settings | None = None,
    agent_config: AgentConfig | None = None,
    conversation_id: str | None = None,
    user_id: int | None = None,
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
    if user_id is not None:
        kwargs["user_id"] = user_id
    return OrchestratorAgent(**kwargs)
