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

import asyncio
import re
import time
from collections.abc import AsyncIterable
from typing import Any, NamedTuple

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
    ConversationStatus,
    LLMConfig,
    ManualTransferRequest,
    Message,
    MessageRole,
    PersonaConstraints,
    STTConfig,
    TTSConfig,
)

# Statuses where the orchestrator itself already wrote a confirmed=True
# tool_executions row at the point of dispatch (_mark_tool_dispatched /
# _run_dispatch_step). Writing another row for response.tool_invoked below
# on these turns would just duplicate that row with confirmed defaulting to
# False -- this set exists so that duplicate write is skipped, while still
# keeping the unconditional provenance write for every other tool_invoked
# turn (ask, reject, error), which is the only record of those turns.
_DISPATCHED_STATUSES = frozenset({ConversationStatus.SUCCESS, ConversationStatus.ENDED})

log = get_logger(__name__)


class WorkflowSyncResult(NamedTuple):
    """Values applied by sync_workflow_state; returned so callers avoid private-attr access."""

    routed_agent: str | None
    completed_steps: list[str]


_CONFIRM_PATTERNS = (
    r"\byes\b",
    r"\bproceed\b",
    r"\bcontinue\b",
    r"\bcontinua\b",
    r"\bcontinúa\b",
    r"\bsure\b",
    r"\bok\b",
    r"\bgo ahead\b",
)
_REJECT_PATTERNS = (
    r"\bno\b",
    r"\bstop\b",
    r"\bcancel\b",
    r"\bwait\b",
)


def _voice_confirmation_decision(content: str) -> str | None:
    """Map spoken text to a workflow/tool confirmation when one is pending."""
    lowered = content.lower()
    if any(re.search(pat, lowered) for pat in _CONFIRM_PATTERNS):
        return "confirm"
    if any(re.search(pat, lowered) for pat in _REJECT_PATTERNS):
        return "reject"
    return None


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

    Reply gate (#153): ``llm_node`` only produces a reply when
    ``request_reply()`` has been called, i.e. the frontend sent a
    ``commit_turn``. The framework's own VAD end-of-turn calls are dropped here
    so they cannot double-fire. The frontend commits either from its own
    silence detection or when nudged by the worker's ``force_commit`` signal,
    which the server-side VAD raises on end-of-speech and is robust to noise.
    """

    def __init__(
        self,
        orchestrator: ConversationOrchestrator,
        *,
        instructions: str | None = None,
        agent_config: AgentConfig | None = None,
        conversation_id: str = "livekit-session",
        user_id: int | None = None,
    ) -> None:
        super().__init__(
            instructions=instructions or "You are TaskOrbit, a helpful voice assistant.",
        )
        self._orchestrator = orchestrator
        self._agent_config = agent_config or _default_agent_config()
        self._conversation_id = conversation_id
        self._user_id = user_id
        self._reply_requested: bool = False
        self._t_commit: float | None = None
        # IDs of the user turns we have already answered (#153). The framework
        # hands llm_node a frozen COPY of the chat context, and a commit can
        # fire before Deepgram delivers the final transcript, so that snapshot
        # may still show only previous turns. We therefore poll the LIVE agent
        # context (self.chat_ctx) and key "have we answered this turn?" off each
        # user message's stable id. This makes a follow-up impossible to drop, a
        # stale re-read impossible to answer twice, and an identical repeat on a
        # NEW turn (new id) still get a reply -- none of which content- or
        # count-based matching got right. The id is added synchronously before
        # the first await so two racing calls cannot both answer one turn.
        self._answered_user_ids: set[str] = set()
        self._locked_intent_name: str | None = None
        self._current_routed_agent: str | None = None
        self._call_ended: bool = False
        # Voice-path handoff hook (#8 Task 6): the most recent agent_transfer
        # target surfaced by the orchestrator. A future LiveKit data-channel
        # handler can read this to notify the client that the active agent
        # changed mid-call without dropping the room.
        self._pending_handoff_target: str | None = None
        # UI-picked manual transfer waiting for the next voice turn (#212).
        self._pending_manual_transfer: ManualTransferRequest | None = None
        # #71: Workflow state for voice path
        self._completed_workflow_steps: list[str] = []
        self._pending_confirmation_id: str | None = None

    def set_manual_transfer(
        self, target_agent_id: str | None, target_agent_name: str | None
    ) -> None:
        """Store a UI-picked agent transfer to apply on the next voice turn (#212).

        The @route menu has no typed message to carry ``manual_transfer``
        during a voice call, so the frontend publishes the pick over the data
        channel and the next turn attaches it to the ConversationRequest.
        Passing (None, None) clears a pending pick (user deselected the menu).
        """
        if target_agent_id is None and target_agent_name is None:
            self._pending_manual_transfer = None
            return
        self._pending_manual_transfer = ManualTransferRequest(
            target_agent_id=target_agent_id,
            target_agent_name=target_agent_name,
        )

    def _consume_pending_manual_transfer(self) -> ManualTransferRequest | None:
        """One-shot: return and clear the pending manual transfer, if any."""
        pending = self._pending_manual_transfer
        self._pending_manual_transfer = None
        return pending

    def sync_workflow_state(
        self,
        *,
        selected_agent: str | None = None,
        completed_workflow_steps: list[str] | None = None,
        clear_pending_confirmation: bool = False,
    ) -> WorkflowSyncResult:
        """Apply workflow state from the text UI so voice turns stay in sync.

        Returns the values that were actually stored so callers can log or act
        on them without reaching into private attributes.
        """
        if selected_agent is not None:
            stripped = selected_agent.strip()
            self._current_routed_agent = stripped if stripped else None
        if completed_workflow_steps is not None:
            self._completed_workflow_steps = list(completed_workflow_steps)
        if clear_pending_confirmation:
            self._pending_confirmation_id = None
        return WorkflowSyncResult(
            routed_agent=self._current_routed_agent,
            completed_steps=list(self._completed_workflow_steps),
        )

    def request_reply(self, t_commit: float | None = None) -> None:
        """Signal that the next ``llm_node`` call should actually produce a reply.

        Call this immediately before ``session.generate_reply()`` from the
        data channel handler. Without it, ``llm_node`` returns empty so that
        AgentSession's preemptive generation does not produce a spurious response.

        ``t_commit`` should be ``time.perf_counter()`` captured at the moment
        the commit_turn data channel message was received, used to measure
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
            # Framework VAD end-of-turn / preemptive call, not triggered by a
            # commit_turn. Drop it so only an explicit commit drives the reply.
            return

        def _live_chat_ctx() -> llm.ChatContext:
            # The chat_ctx ARGUMENT is a frozen copy taken when the reply was
            # created (livekit agent_activity copies it before llm_node), so a
            # transcript that lands a moment later never appears in it. Read the
            # agent's LIVE context instead, which the framework appends finalized
            # user turns to. Fall back to the argument when the live context is
            # unavailable (unit tests build the agent without an AgentSession).
            live = getattr(self, "chat_ctx", None)
            if live is not None and getattr(live, "items", None):
                return live
            return chat_ctx

        def _unanswered_user_turn() -> tuple[str, str] | None:
            # (id, text) of the most recent non-empty user message we have not
            # already answered, else None (empty context, or the latest turn is
            # one we already replied to -- a stale or duplicate trigger).
            # Latest-wins: we return on the FIRST (newest) user message and do
            # not fall back to an older un-answered one. If a user fires two
            # turns before either is answered, we answer the newer and skip the
            # older (whose text is still in context for the orchestrator to see)
            # -- matching the framework's own new-turn-interrupts-old behavior.
            for item in reversed(getattr(_live_chat_ctx(), "items", [])):
                if getattr(item, "role", None) != "user":
                    continue
                text = _extract_text(item)
                if not text.strip():
                    continue
                msg_id = str(getattr(item, "id", None) or text)
                return None if msg_id in self._answered_user_ids else (msg_id, text)
            return None

        # Race guard (#153): a commit_turn (FE silence detection or the
        # server-VAD force_commit) can fire before Deepgram delivers the final
        # transcript for THIS turn, so the live context still shows only the
        # already-answered previous turn. Poll the live context until a genuinely
        # new user turn (an id we have not answered) lands, up to ~2.5s to cover
        # the observed Deepgram transcript delay (~1.4s, occasionally longer).
        turn = _unanswered_user_turn()
        _waited = 0
        while turn is None and _waited < 25:
            await asyncio.sleep(0.1)
            turn = _unanswered_user_turn()
            _waited += 1
        if turn is None:
            # No new turn materialised in time. Leave the gate armed so the next
            # trigger (the framework VAD end-of-turn for this same turn, or a
            # re-commit) retries instead of permanently dropping the reply. Clear
            # the commit timestamp so a later armed retry that answers without a
            # fresh commit_turn does not report this turn's stale latency.
            self._t_commit = None
            log.info("voice_turn_awaiting_transcript", conversation_id=self._conversation_id)
            return

        msg_id, user_text = turn
        # Claim this turn synchronously -- no await between the membership check
        # and the add -- so two concurrent llm_node calls cannot both answer it.
        if msg_id in self._answered_user_ids:
            return
        self._answered_user_ids.add(msg_id)
        self._reply_requested = False

        # Build the request from the same live context we claimed the turn from.
        messages = _convert_chat_ctx_to_messages(_live_chat_ctx())
        last_user = next((m for m in reversed(messages) if m.role == MessageRole.USER), None)

        log.info(
            "llm_active",
            provider=self._agent_config.llm.provider,
            model=self._agent_config.llm.model,
            conversation_id=self._conversation_id,
        )

        # STT latency: time from commit_turn received to transcript available in llm_node.
        # llm_node is only invoked after AgentSession has a final Deepgram transcript,
        # so this measures how long STT processing took after the user committed their turn.
        if self._t_commit is not None:
            stt_elapsed = time.perf_counter() - self._t_commit
            get_metrics().pipeline_latency_seconds.labels(stage="stt_processing").observe(
                stt_elapsed
            )
            log.debug("stt_processing_complete", latency_ms=round(stt_elapsed * 1000, 1))

        log.debug("stt_transcript_received", length=len(user_text))

        # #71: Simple voice-path confirmation detection. If we have a pending
        # confirmation, we check if the user said something affirmative.
        decision = None
        if self._pending_confirmation_id and last_user:
            decision = _voice_confirmation_decision(last_user.content)

        # #212: a manual transfer picked from the @route menu applies exactly
        # once, on this turn; the orchestrator's step-0a short-circuit swaps
        # the conversation to the picked agent.
        manual_transfer = self._consume_pending_manual_transfer()

        request = ConversationRequest(
            conversation_id=self._conversation_id,
            agent_config=self._agent_config,
            messages=messages,
            current_intent_name=self._locked_intent_name,
            selected_agent=self._current_routed_agent,
            completed_workflow_steps=self._completed_workflow_steps,
            confirmation_id=self._pending_confirmation_id if decision else None,
            decision=decision,
            manual_transfer=manual_transfer,
        )
        from taskorbit.types import ToolType as _ToolType

        # Stream the orchestrator response: yield str chunks to TTS immediately,
        # capture the final ConversationResponse for state updates below.
        # The DB session stays open across the entire stream so that manual
        # transfers and custom-agent DB lookups work in the voice path.
        response = None
        chunk_index = 0
        try:
            async with AsyncSessionLocal() as db:
                async for item in self._orchestrator.process_message_stream(
                    request, db=db, user_id=self._user_id
                ):
                    if isinstance(item, str):
                        if chunk_index == 0 and self._t_commit is not None:
                            _first_chunk_latency = time.perf_counter() - self._t_commit
                            log.debug(
                                "llm_first_chunk",
                                latency_ms=round(_first_chunk_latency * 1000, 1),
                            )
                        log.debug("llm_stream_chunk", index=chunk_index, chars=len(item))
                        chunk_index += 1
                        yield item
                    else:
                        response = item
        except Exception as exc:
            log.error(
                "voice_turn_orchestrator_failed",
                error=str(exc),
                conversation_id=self._conversation_id,
            )
            raise

        # Speak the ConversationResponse.reply via TTS when it carries the
        # user-facing text. Two cases:
        #  1) Early-exit paths (clarification, confirmation, handoff block,
        #     end-call, error-before-any-chunk) produce no str chunks, so
        #     chunk_index == 0 and the reply is all we have.
        #  2) Mid-stream provider failure (#197): chunks already flowed to TTS,
        #     then the orchestrator yielded status="error" with a polite reply.
        #     Without this branch the user hears half a sentence then silence.
        if response is not None and response.reply and response.reply.content:
            if chunk_index == 0 or response.status == "error":
                yield response.reply.content

        if response is None:
            return

        # On error responses (#197) the orchestrator emits a bare
        # ConversationResponse with defaults for workflow-state fields.
        # Preserving the incoming state avoids stranding the session mid-flow
        # after a transient provider blip.
        if response.status != "error":
            self._locked_intent_name = response.locked_intent_name
            self._completed_workflow_steps = response.completed_workflow_steps
            if (
                response.status in {"confirmation_required", "workflow_confirmation_required"}
                and response.confirmation
            ):
                self._pending_confirmation_id = response.confirmation.confirmation_id
            else:
                self._pending_confirmation_id = None

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
                # Persist slot extractions only when the tool actually fired, and
                # attribute them to that tool — mirrors the text path. Partial fills
                # (extracted_slots set but no tool_invoked) are surfaced to the UI for
                # progress but not saved, which also avoids the generic "orchestrator"
                # provenance label and duplicate per-turn rows.
                if response.extracted_slots and response.tool_invoked:
                    await create_slot_extractions(
                        db,
                        conversation_id=conv_id,
                        tool_id=response.tool_invoked.id,
                        slots=response.extracted_slots,
                    )
                # Skip on success/ended: the orchestrator's own dispatch path
                # (_mark_tool_dispatched) already wrote a confirmed=True row
                # for this exact turn, so writing another one here would just
                # be a duplicate. Ask/reject/error turns still land here since
                # this is the only record of those.
                if response.tool_invoked and response.status not in _DISPATCHED_STATUSES:
                    tool_duration_ms = (
                        response.latency_ms.tool_call if response.latency_ms is not None else None
                    )
                    await create_tool_execution(
                        db,
                        conversation_id=conv_id,
                        tool_id=response.tool_invoked.id,
                        tool_type=response.tool_invoked.type.value,
                        result={"extracted_slots": response.extracted_slots}
                        if response.extracted_slots
                        else None,
                        duration_ms=tool_duration_ms,
                    )
        except Exception as exc:
            log.error(
                "voice_turn_db_persist_failed",
                error=str(exc),
                conversation_id=self._conversation_id,
            )
        else:
            log.info("voice_turn_db_persist_ok", conversation_id=conv_id)

        if response.status == "ended":
            self._call_ended = True
        status = "success" if response.status == "success" else "error"
        get_metrics().voice_pipeline_requests_total.labels(
            handler="/v1/conversations/process", status=status
        ).inc()

        # Surface agent_transfer for the voice path (#8 Task 6 AC7).
        if (
            response.tool_invoked is not None
            and response.tool_invoked.type == _ToolType.AGENT_TRANSFER
            # Publish only COMPLETED transfers: tool_invoked is also set on
            # confirmation_required (the ask turn) and rejected responses,
            # which must not swap the card or reroute the worker (#212).
            and response.status == "success"
        ):
            targets = response.tool_invoked.parameters.get("targets") or []
            if targets:
                self._pending_handoff_target = str(targets[0])
                # The conversation is now routed to the target: without this,
                # selected_agent stays on the entry agent and the transfer
                # re-fires (and re-publishes) on every subsequent turn (#212).
                self._current_routed_agent = self._pending_handoff_target
                log.info(
                    "voice_agent_handoff_pending",
                    target=self._pending_handoff_target,
                    selected_agent=response.selected_agent,
                    conversation_id=self._conversation_id,
                )

        # Manual voice transfer (#212): surface the swap only once the
        # orchestrator confirms the transfer completed, so a cancelled or
        # failed turn can never swap the card away from the real agent.
        if manual_transfer is not None:
            expected = manual_transfer.target_agent_id or manual_transfer.target_agent_name
            if response.status == "error":
                log.warning(
                    "voice_manual_transfer_failed",
                    target=expected,
                    error=response.error,
                    conversation_id=self._conversation_id,
                )
            else:
                self._pending_handoff_target = expected
                log.info(
                    "voice_manual_transfer_applied",
                    target=expected,
                    selected_agent=response.selected_agent,
                    conversation_id=self._conversation_id,
                )

        if self._t_commit is not None:
            elapsed = time.perf_counter() - self._t_commit
            get_metrics().voice_turn_latency_seconds.observe(elapsed)
            log.info("voice_turn_complete", latency_ms=round(elapsed * 1000, 1))
            self._t_commit = None
