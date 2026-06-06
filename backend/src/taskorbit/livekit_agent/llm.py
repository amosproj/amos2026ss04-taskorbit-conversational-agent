"""Custom LLM bridge — adapts ConversationOrchestrator to AgentSession.

Rather than implementing the full ``livekit.agents.llm.LLM`` provider
interface (which expects streaming chat completions, function-call
parsing, usage stats, etc.), we override the much smaller ``llm_node``
hook on ``Agent``. The hook is the single point ``AgentSession`` uses to
generate assistant replies, so customising it is the cleanest way to
plug a non-LLM backend (or a future real LLM) into the voice pipeline.

The orchestrator stays the source of truth for "what should the
assistant say next?". Today it's an echo stub; swapping in a real LLM
later only requires changing ``ConversationOrchestrator.process_message``
— this adapter does not need to change.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterable
from typing import Any

from livekit.agents import Agent, FunctionTool, ModelSettings, llm

from taskorbit.database import AsyncSessionLocal
from taskorbit.database.crud import (
    create_conversation,
    create_conversation_message,
    create_slot_extractions,
    create_tool_execution,
    get_conversation,
)
from taskorbit.logging.setup import get_logger
from taskorbit.observability.metrics import get_metrics
from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import (
    AgentConfig,
    ConversationRequest,
    LLMConfig,
    Message,
    MessageRole,
    PersonaConstraints,
    STTConfig,
    TTSConfig,
)

log = get_logger(__name__)


def _default_agent_config() -> AgentConfig:
    """Minimal AgentConfig used when no agent metadata is attached.

    The voice worker doesn't have access to the frontend agent config
    today (token metadata wiring is a future task). For now we synthesise
    a plain config so the orchestrator can still produce a reply.

    Mirrors the John Doe TechStore preset from frontend/src/lib/mockAgents.ts,
    including persona_constraints (ticket #69) so the voice path receives
    the same guardrails as the text path until token metadata wiring lands.
    """
    return AgentConfig(
        id="livekit-default",
        name="John Doe",
        persona="A friendly and professional customer service agent for TechStore.",
        greeting="Hi there! I'm John from TechStore customer support.",
        stt=STTConfig(),
        llm=LLMConfig(),
        tts=TTSConfig(),
        tools=[],
        persona_constraints=PersonaConstraints(
            scope=(
                "TechStore customer service: account setup, order tracking, "
                "returns, product questions, and technical support."
            ),
            out_of_scope=[
                "medical advice",
                "therapy or emotional counseling",
                "legal advice",
                "financial advice",
            ],
            refusal_template=(
                "I'm here to help with TechStore questions — for that I'd "
                "recommend reaching out to a qualified professional. Is there "
                "anything TechStore-related I can help with?"
            ),
        ),
    )


def _convert_chat_ctx_to_messages(chat_ctx: llm.ChatContext) -> list[Message]:
    """Translate AgentSession's ChatContext into the orchestrator's Message list.

    Only user/assistant/system entries with plain text content are kept —
    function-call items are ignored because the orchestrator is text-only.
    """
    messages: list[Message] = []
    for item in chat_ctx.items:
        role = getattr(item, "role", None)
        if role not in ("user", "assistant", "system"):
            continue
        text = _extract_text(item)
        if not text:
            continue
        try:
            messages.append(
                Message(role=MessageRole(role), content=text),
            )
        except ValueError:
            continue
    return messages


def _extract_text(item: Any) -> str:
    """Best-effort plain-text extractor for ChatMessage-like items.

    ``content`` is typically ``str | list[str | ImageContent | AudioContent]``;
    we keep only the string parts and join them.
    """
    content = getattr(item, "content", None)
    if isinstance(content, str):
        return _normalize_text(content)
    if isinstance(content, list):
        parts: list[str] = []
        for entry in content:
            if isinstance(entry, str):
                parts.append(entry)
        return _normalize_text(" ".join(parts))
    text_attr = getattr(item, "text_content", None)
    if isinstance(text_attr, str):
        return _normalize_text(text_attr)
    return ""


def _normalize_text(text: str) -> str:
    """Replace common Unicode punctuation variants with ASCII equivalents.

    STT providers (e.g. Deepgram) can emit Unicode dashes and smart quotes
    in transcriptions. Replacing them prevents UnicodeEncodeError when the
    text is passed to LLM HTTP clients that use ASCII-only JSON serialisation.
    """
    return (
        text.replace("—", "-")  # em dash
        .replace("–", "-")  # en dash
        .replace("‘", "'")  # left single quotation mark
        .replace("’", "'")  # right single quotation mark
        .replace("“", '"')  # left double quotation mark
        .replace("”", '"')  # right double quotation mark
        .strip()
    )


class OrchestratorAgent(Agent):
    """``Agent`` subclass that routes LLM inference through ConversationOrchestrator.

    AgentSession will call ``llm_node`` once per user turn with the full
    chat context. We translate that context into a ``ConversationRequest``,
    hand it to the orchestrator, and yield the assistant reply as a single
    ``ChatChunk``. Streaming is left for a real LLM integration; the
    pipeline can stream this single chunk into the TTS without issue.

    Push-to-talk guard: ``llm_node`` only processes when ``request_reply()``
    has been called first. Preemptive generation calls from AgentSession
    are silently dropped, preventing double responses.
    """

    def __init__(
        self,
        orchestrator: ConversationOrchestrator,
        *,
        instructions: str | None = None,
        agent_config: AgentConfig | None = None,
        conversation_id: str = "livekit-session",
    ) -> None:
        super().__init__(
            instructions=instructions or "You are TaskOrbit, a helpful voice assistant.",
        )
        self._orchestrator = orchestrator
        self._agent_config = agent_config or _default_agent_config()
        self._conversation_id = conversation_id
        self._reply_requested: bool = False
        self._t_commit: float | None = None
        self._locked_intent_name: str | None = None
        self._current_routed_agent: str = ""
        # Voice-path handoff hook (#8 Task 6): the most recent agent_transfer
        # target surfaced by the orchestrator. A future LiveKit data-channel
        # handler can read this to notify the client that the active agent
        # changed mid-call without dropping the room.
        self._pending_handoff_target: str | None = None

    def request_reply(self, t_commit: float | None = None) -> None:
        """Signal that the next ``llm_node`` call should actually produce a reply.

        Call this immediately before ``session.generate_reply()`` from the
        data channel handler. Without it, ``llm_node`` returns empty so that
        AgentSession's preemptive generation does not produce a spurious response.

        ``t_commit`` should be ``time.perf_counter()`` captured at the moment
        the commit_turn data channel message was received — used to measure
        end-to-end voice turn latency.
        """
        self._reply_requested = True
        self._t_commit = t_commit if t_commit is not None else time.perf_counter()

    async def llm_node(  # type: ignore[override]
        self,
        chat_ctx: llm.ChatContext,
        tools: list[FunctionTool],  # type: ignore[type-arg]
        model_settings: ModelSettings,
    ) -> AsyncIterable[llm.ChatChunk | str]:
        """Generate the assistant reply for the current turn.

        We ignore ``tools`` and ``model_settings`` here: the orchestrator
        owns its own tool dispatch and the response is plain text. If a
        real LLM is wired in later, this method should change to delegate
        back to ``Agent.default.llm_node`` instead.
        """
        if not self._reply_requested:
            # Preemptive generation call — not triggered by Send. Drop it.
            return
        self._reply_requested = False

        # STT latency: time from commit_turn received to transcript available in llm_node.
        # llm_node is only invoked after AgentSession has a final Deepgram transcript,
        # so this measures how long STT processing took after the user committed their turn.
        if self._t_commit is not None:
            stt_elapsed = time.perf_counter() - self._t_commit
            get_metrics().pipeline_latency_seconds.labels(stage="stt_processing").observe(
                stt_elapsed
            )
            log.debug("stt_processing_complete", latency_ms=round(stt_elapsed * 1000, 1))

        messages = _convert_chat_ctx_to_messages(chat_ctx)
        last_user = next((m for m in reversed(messages) if m.role == MessageRole.USER), None)
        if last_user:
            log.debug("stt_transcript_received", length=len(last_user.content))
        request = ConversationRequest(
            conversation_id=self._conversation_id,
            agent_config=self._agent_config,
            messages=messages,
            current_intent_name=self._locked_intent_name,
        )
        response = await self._orchestrator.process_message(request)
        self._locked_intent_name = response.locked_intent_name
        if response.selected_agent:
            self._current_routed_agent = response.selected_agent

        # Persist the voice turn to the database so conversation history is
        # available regardless of whether the user interacted via text or voice.
        try:
            async with AsyncSessionLocal() as db:
                conv_id = self._conversation_id
                log.debug("voice_turn_db_persist_start", conversation_id=conv_id)
                if not await get_conversation(db, conv_id):
                    conv = await create_conversation(
                        db,
                        agent_id=self._agent_config.id,
                        agent_name=self._agent_config.name,
                        id=conv_id,
                    )
                    if conv is None:
                        log.error("voice_turn_conversation_create_failed", conversation_id=conv_id)
                if last_user:
                    await create_conversation_message(
                        db,
                        conversation_id=conv_id,
                        role=last_user.role.value,
                        content=last_user.content,
                    )
                if response.reply:
                    await create_conversation_message(
                        db,
                        conversation_id=conv_id,
                        role=response.reply.role.value,
                        content=response.reply.content,
                    )
                if response.extracted_slots:
                    tool_id = response.tool_invoked.id if response.tool_invoked else "orchestrator"
                    await create_slot_extractions(
                        db,
                        conversation_id=conv_id,
                        tool_id=tool_id,
                        slots=response.extracted_slots,
                    )
                if response.tool_invoked:
                    await create_tool_execution(
                        db,
                        conversation_id=conv_id,
                        tool_id=response.tool_invoked.id,
                        tool_type=response.tool_invoked.type.value,
                        result={"extracted_slots": response.extracted_slots}
                        if response.extracted_slots
                        else None,
                    )
        except Exception as exc:
            log.error(
                "voice_turn_db_persist_failed",
                error=str(exc),
                conversation_id=self._conversation_id,
            )
        else:
            log.info("voice_turn_db_persist_ok", conversation_id=conv_id)

        status = "success" if response.status == "success" else "error"
        get_metrics().voice_pipeline_requests_total.labels(
            handler="/v1/conversations/process", status=status
        ).inc()

        # Surface agent_transfer for the voice path (#8 Task 6 AC7). The
        # worker reads self._pending_handoff_target after generate_reply()
        # completes and publishes it on the taskorbit.agent_handoff topic
        # so the FE swaps the active agent without dropping the LiveKit room.
        from taskorbit.types import ToolType as _ToolType

        if (
            response.tool_invoked is not None
            and response.tool_invoked.type == _ToolType.AGENT_TRANSFER
        ):
            targets = response.tool_invoked.parameters.get("targets") or []
            if targets:
                self._pending_handoff_target = str(targets[0])
                log.info(
                    "voice_agent_handoff_pending",
                    target=self._pending_handoff_target,
                    selected_agent=response.selected_agent,
                    conversation_id=self._conversation_id,
                )

        text = response.reply.content or ""

        if self._t_commit is not None:
            elapsed = time.perf_counter() - self._t_commit
            get_metrics().voice_turn_latency_seconds.observe(elapsed)
            log.info("voice_turn_complete", latency_ms=round(elapsed * 1000, 1))
            self._t_commit = None

        if not text:
            return
        yield text
