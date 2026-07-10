"""Orchestration engine — the core of TaskOrbit.

ConversationOrchestrator is the single entry point for processing a user
message. It enforces the key architectural invariant: the LLM only ever
sees the context for the *currently active* task, never the full agent
config. This prevents prompt drift and keeps the agent grounded.

Flow per message:
  0a. Manual transfer short-circuit: if request.manual_transfer is set, bypass
      steps 1–6 entirely and route directly via _handle_manual_transfer.
  1. Detect intent via keyword routing.
  2. Select the agent via AgentRegistry.
  3. Determine which tool (if any) should be in scope right now.
  3b. Extract slots from conversation history using SlotExtractor.
  4. Build a system prompt augmented with slot collection progress.
  5. Call the LLM provider with a timeout (configurable via settings).
  5b. Execute DataExtractionTool when all required slots are filled.
  6. Return a ConversationResponse with intent, agent, slot, and status fields.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from taskorbit.agents import BaseAgent

from taskorbit.agents import AgentRegistry
from taskorbit.config import Settings, get_settings
from taskorbit.integrations.llm.errors import LLMConfigError, LLMError, LLMTimeoutError
from taskorbit.integrations.llm.scope_check import is_message_in_scope
from taskorbit.intent import _KNOWN_INTENTS, IntentResult, IntentRouter
from taskorbit.logging.setup import get_logger
from taskorbit.observability.metrics import get_metrics
from taskorbit.types import (
    AgentConfig,
    ConfirmationResponsePayload,
    ContextLimitConfig,
    ConversationRequest,
    ConversationResponse,
    ConversationStatus,
    LLMConfig,
    Message,
    MessageRole,
    PipelineLatencyMs,
    ToolDefinition,
    ToolType,
)
from taskorbit.workflow_rules import (
    expand_workflow_dependencies,
    resolve_workflow_dependencies,
)

logger = get_logger(__name__)


def _effective_selected_agent(selected_agent: str | None) -> str | None:
    """Normalize empty strings from the voice path to None."""
    if selected_agent is None:
        return None
    stripped = selected_agent.strip()
    return stripped if stripped else None


def _selected_agent_matches_dep(selected_agent: str | None, dep_id: str) -> bool:
    """True when the session is already executing a prerequisite agent step."""
    if not selected_agent:
        return False
    dep_registry = AgentRegistry.get_agent_name_for_id(dep_id)
    return selected_agent == dep_id or selected_agent == dep_registry


def _resolve_missing_dependencies(
    request: ConversationRequest,
    intent: IntentResult,
) -> tuple[list[str], list[str], list[str]]:
    """Return (direct_dependencies, effective_dependencies, missing_dependencies)."""
    direct = resolve_workflow_dependencies(
        request.agent_config,
        intent_name=intent.name,
        intent_agent_name=intent.agent_name,
    )
    effective = expand_workflow_dependencies(direct, request.dependency_configs)
    missing = [dep for dep in effective if dep not in request.completed_workflow_steps]
    return direct, effective, missing


def _workflow_prereq_confirmation_message(entry_name: str, dep_name: str) -> str:
    return (
        f"Before we proceed with {entry_name}, I'll need to complete some "
        f"prerequisite steps regarding {dep_name}. Shall I start with that?"
    )


def _workflow_prereq_start_ack(next_dep: str) -> str:
    return f"Understood. Let's start with the {next_dep.replace('-', ' ')} steps."


def _is_executing_workflow_prerequisite(
    request: ConversationRequest,
    intent: IntentResult,
) -> bool:
    """True after Proceed when the next missing prerequisite is already selected."""
    if not request.selected_agent or not request.dependency_configs:
        return False

    _, _, missing = _resolve_missing_dependencies(request, intent)
    return bool(missing) and _selected_agent_matches_dep(request.selected_agent, missing[0])


def _resolve_intent_after_clarification_gate(
    request: ConversationRequest,
    intent: IntentResult,
) -> IntentResult:
    """Keep workflow turns moving when follow-ups like ``continue`` fail intent gating."""
    if not intent.requires_clarification:
        return intent
    if not _is_executing_workflow_prerequisite(request, intent):
        return intent
    if request.current_intent_name and request.current_intent_name in _KNOWN_INTENTS:
        return dataclass_replace(_KNOWN_INTENTS[request.current_intent_name], confidence=1.0)
    return dataclass_replace(intent, requires_clarification=False, confidence=1.0)


def _workflow_ui_selected_agent(request: ConversationRequest) -> str | None:
    """Stable workflow routing id for the UI — never intent registry names like general_inquiry."""
    return request.selected_agent or request.agent_config.id or None


def _normalize_field_key(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure each field dict has a ``name`` key.

    Frontend ``DataExtractionTool.params`` uses ``variable_name`` while the
    backend ``SlotExtractor`` expects ``name``.  This helper bridges the two
    schemas so tool-configured fields work end-to-end.
    """
    return [{**f, "name": f.get("name") or f.get("variable_name", "")} for f in fields]


def _seconds_to_ms(seconds: float | None) -> float | None:
    """Convert perf_counter seconds to rounded milliseconds, or None when unset."""
    return round(seconds * 1000, 1) if seconds is not None else None


def _build_pipeline_latency_ms(
    *,
    llm_elapsed: float | None = None,
    tool_elapsed: float | None = None,
    total_elapsed: float | None = None,
) -> PipelineLatencyMs:
    """Assemble per-stage latency fields for ConversationResponse (#68)."""
    return PipelineLatencyMs(
        llm_call=_seconds_to_ms(llm_elapsed),
        tool_call=_seconds_to_ms(tool_elapsed),
        total=_seconds_to_ms(total_elapsed),
    )


@dataclass
class _DispatchResult:
    """Result of _run_dispatch_step; non-None early_response means short-circuit."""

    early_response: ConversationResponse | None
    tool_data: dict[str, Any]
    response_status: ConversationStatus
    llm_text_override: str | None
    tool_call_elapsed: float | None = None
    # #212: on a successful agent_transfer, a copy of the tool whose targets
    # hold the RESOLVED canonical id, so the voice publish and the FE swap
    # never see the raw config string.
    tool_invoked_override: ToolDefinition | None = None


class ConversationOrchestrator:
    """Routes messages through intent detection → agent → LLM → response."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._intent_router = IntentRouter()

    async def process_message(
        self,
        request: ConversationRequest,
        db: AsyncSession | None = None,
        user_id: int | None = None,
    ) -> ConversationResponse:
        """Main entry point called by the API layer and agent workers."""
        _pipeline_start = time.perf_counter()
        try:
            # 0a. Manual transfer: UI-initiated handoff bypasses intent detection entirely.
            if request.manual_transfer and (
                request.manual_transfer.target_agent_id or request.manual_transfer.target_agent_name
            ):
                return await self._handle_manual_transfer(request, db, user_id=user_id)

            if db is not None and user_id is not None:
                from taskorbit.database.crud import enrich_request_dependency_configs

                request = await enrich_request_dependency_configs(request, db, user_id)

            effective_selected = _effective_selected_agent(request.selected_agent)
            if effective_selected != request.selected_agent:
                request = request.model_copy(update={"selected_agent": effective_selected})

            last_user = next(
                (m for m in reversed(request.messages) if m.role == MessageRole.USER),
                None,
            )
            if not last_user or not last_user.content.strip():
                raise ValueError("No user message content found in request.")

            # 0. User-initiated end-call: if the caller says goodbye and the agent
            # has an end_call tool configured, skip the normal pipeline entirely.
            from taskorbit.types import ConversationStatus, ToolType

            end_call_tool = next(
                (t for t in request.agent_config.tools if t.type == ToolType.END_CALL),
                None,
            )
            logger.debug(
                "end_call_check",
                conversation_id=request.conversation_id,
                tool_found=end_call_tool is not None,
                tools_count=len(request.agent_config.tools),
                tool_types=[t.type for t in request.agent_config.tools],
                user_requested=self._user_requested_end_call(last_user.content),
            )
            if end_call_tool and self._user_requested_end_call(last_user.content):
                try:
                    farewell = await asyncio.wait_for(
                        self._call_llm(
                            f"You are {request.agent_config.name}. "
                            f"Persona: {request.agent_config.persona}\n"
                            "The user wants to end the conversation. "
                            "Say a brief, warm farewell in one sentence.",
                            request.messages,
                            request.agent_config.llm,
                        ),
                        timeout=self._settings.llm_timeout_seconds,
                    )
                except Exception:  # noqa: BLE001
                    farewell = "Goodbye! Take care."
                    logger.warning(
                        "end_call_farewell_llm_failed",
                        conversation_id=request.conversation_id,
                        fallback=farewell,
                    )
                _, tool_elapsed = await self._dispatch_tool(end_call_tool, {})
                logger.info(
                    "end_call_user_initiated",
                    conversation_id=request.conversation_id,
                    tool_call_latency_ms=_seconds_to_ms(tool_elapsed),
                )
                return ConversationResponse(
                    conversation_id=request.conversation_id,
                    reply=self._make_assistant_message(farewell),
                    status=ConversationStatus.ENDED,
                    selected_intent="",
                    selected_agent="",
                    tool_invoked=end_call_tool,
                    latency_ms=_build_pipeline_latency_ms(tool_elapsed=tool_elapsed),
                )

            # 0b. Pre-intent scope short-circuit: refuse clearly off-topic turns before
            # intent routing or the clarification gate (#168 follow-up).
            refusal_response = self._entry_scope_refusal(
                message=last_user.content,
                request=request,
                stage="pre_intent",
            )
            if refusal_response is not None:
                return refusal_response

            # 1. Detect intent — reuse locked intent when set, but still run the
            # classifier to allow genuine topic changes to break the lock.
            if request.current_intent_name and request.current_intent_name in _KNOWN_INTENTS:
                fresh = await self._intent_router.detect(
                    last_user.content,
                    request.messages,
                    self._call_llm_json,
                    request.agent_config.llm,
                )
                if (
                    fresh.name != request.current_intent_name
                    and fresh.confidence >= self._intent_router._threshold
                    and not fresh.requires_clarification
                ):
                    intent = fresh
                    logger.info(
                        "intent_lock_broken",
                        old=request.current_intent_name,
                        new=intent.name,
                        confidence=intent.confidence,
                        conversation_id=request.conversation_id,
                    )
                else:
                    intent = dataclass_replace(
                        _KNOWN_INTENTS[request.current_intent_name], confidence=1.0
                    )
                    logger.info(
                        "intent_locked",
                        intent=intent.name,
                        conversation_id=request.conversation_id,
                    )
            else:
                intent = await self._intent_router.detect(
                    last_user.content,
                    request.messages,
                    self._call_llm_json,
                    request.agent_config.llm,
                )
                logger.info(
                    "intent_detected",
                    intent=intent.name,
                    confidence=intent.confidence,
                    conversation_id=request.conversation_id,
                )

            intent = _resolve_intent_after_clarification_gate(request, intent)

            # Short-circuit: ask for clarification instead of guessing
            if intent.requires_clarification:
                from taskorbit.intent import _CLARIFICATION_REPLY

                return ConversationResponse(
                    conversation_id=request.conversation_id,
                    reply=self._make_assistant_message(_CLARIFICATION_REPLY),
                    status=ConversationStatus.CLARIFICATION,
                    selected_intent=intent.name,
                    selected_agent="",
                    intent_confidence=intent.confidence,
                )

            # 2. Select agent based on detected intent or turn-1 locking
            handoff_blocked = False
            allowed_agent_names: list[str] = []
            if not request.selected_agent:
                # AC #71: Turn 1 is ALWAYS locked to the configured entry agent.
                # This ensures the greeting and initial persona match the config.
                agent = AgentRegistry.create(request.agent_config, self)
                logger.info(
                    "entry_agent_locked",
                    agent=agent.agent_name,
                    conversation_id=request.conversation_id,
                )
            else:
                # Normal routing for subsequent turns
                agent = await AgentRegistry.create_by_name(
                    intent.agent_name, request.agent_config, self, db=db, user_id=user_id
                )

                # #71: Handoff check will be enforced after workflow dependency checks.
                # We still compute the allowed list now for later use.
                allowed_agent_names = []
                if (
                    intent.agent_name != request.selected_agent
                    and request.agent_config.allowed_handoffs
                ):
                    allowed_agent_names = [
                        AgentRegistry.get_agent_name_for_id(cfg_id)
                        for cfg_id in request.agent_config.allowed_handoffs
                    ]

            # Resolve workflow dependencies BEFORE enforcing handoff rules.
            # This ensures DEMO-1 (prerequisite flow) is offered even when a
            # requested handoff would otherwise be blocked.
            #
            # Note: _resolve_missing_dependencies may also have been called inside
            # _is_executing_workflow_prerequisite (via the clarification gate above)
            # with the *pre-gate* intent. We cannot reuse that result here because
            # _resolve_intent_after_clarification_gate can return a *different* intent
            # (from _KNOWN_INTENTS[current_intent_name]) — making the two calls
            # operate on different intents. Correctness requires recomputing here with
            # the post-gate intent that the rest of this pipeline actually uses.
            direct_dependencies, effective_dependencies, missing_dependencies = (
                _resolve_missing_dependencies(request, intent)
            )

            logger.debug(
                "workflow_dependency_check",
                direct=direct_dependencies,
                effective=effective_dependencies,
                completed=request.completed_workflow_steps,
                missing=missing_dependencies,
                selected=request.selected_agent,
            )

            executing_prereq_id: str | None = None
            if missing_dependencies:
                next_dep = missing_dependencies[0]
                executing_prereq = _selected_agent_matches_dep(request.selected_agent, next_dep)

                if executing_prereq:
                    # User already confirmed — run the prerequisite agent, do not re-prompt.
                    executing_prereq_id = next_dep

                    # AC #71: Resolve the prerequisite agent's config from dependency_configs.
                    # This ensures the LLM sees the CORRECT persona and tools for the prerequisite.
                    dep_config = request.dependency_configs.get(next_dep)
                    if not dep_config:
                        # Deadlock guard (AC #9): If we can't resolve the config for a required
                        # dependency, we cannot proceed. Block the handoff and stay on current agent.
                        logger.error(
                            "workflow_dependency_config_missing",
                            dependency=next_dep,
                            conversation_id=request.conversation_id,
                        )
                        handoff_blocked = True
                        # AC #9: Reset agent to the entry agent so we don't accidentally act as
                        # an unconfigured prerequisite or the requested (blocked) handoff target.
                        agent = AgentRegistry.create(request.agent_config, self)
                    else:
                        agent = AgentRegistry.create(dep_config, self)
                        logger.info(
                            "workflow_dependency_executing",
                            dependency=next_dep,
                            agent=agent.agent_name,
                            conversation_id=request.conversation_id,
                        )
                else:
                    logger.info(
                        "workflow_dependency_missing",
                        dependency=next_dep,
                        conversation_id=request.conversation_id,
                    )

                    is_decision_for_this_workflow = (
                        request.confirmation_id == f"workflow_{next_dep}"
                    )
                    has_decision = is_decision_for_this_workflow and request.decision is not None

                    if not has_decision:
                        # Deadlock guard (AC #9): If we can't resolve the metadata for the prompt,
                        # we still offer the handoff but falling back to the ID name.
                        dep_name = next_dep.replace("-", " ")
                        dep_config = request.dependency_configs.get(next_dep)
                        if dep_config:
                            dep_name = dep_config.name

                        return ConversationResponse(
                            conversation_id=request.conversation_id,
                            reply=self._make_assistant_message(
                                _workflow_prereq_confirmation_message(
                                    request.agent_config.name, dep_name
                                )
                            ),
                            status=ConversationStatus.WORKFLOW_CONFIRMATION_REQUIRED,
                            confirmation=ConfirmationResponsePayload(
                                confirmation_id=f"workflow_{next_dep}",
                                action=f"Start {next_dep} workflow",
                                description=f"Prerequisite: {dep_name}",
                            ),
                            selected_intent=intent.name,
                            selected_agent=_workflow_ui_selected_agent(request) or "",
                            intent_confidence=intent.confidence,
                            locked_intent_name=intent.name,
                            completed_workflow_steps=request.completed_workflow_steps,
                        )

                    if request.decision == "reject":
                        logger.info(
                            "workflow_dependency_rejected",
                            dependency=next_dep,
                            conversation_id=request.conversation_id,
                        )
                        return ConversationResponse(
                            conversation_id=request.conversation_id,
                            reply=self._make_assistant_message(
                                "Understood. I can't proceed without those prerequisite steps. Is there anything else I can help you with?"
                            ),
                            status=ConversationStatus.REJECTED,
                            selected_intent=intent.name,
                            selected_agent=_workflow_ui_selected_agent(request) or "",
                            locked_intent_name=intent.name,
                            completed_workflow_steps=request.completed_workflow_steps,
                        )

                    logger.info(
                        "workflow_dependency_confirmed",
                        dependency=next_dep,
                        conversation_id=request.conversation_id,
                    )
                    return ConversationResponse(
                        conversation_id=request.conversation_id,
                        reply=self._make_assistant_message(_workflow_prereq_start_ack(next_dep)),
                        status=ConversationStatus.SUCCESS,
                        selected_agent=next_dep,
                        selected_intent=intent.name,
                        intent_confidence=1.0,
                        locked_intent_name=intent.name,
                        completed_workflow_steps=request.completed_workflow_steps,
                    )

            elif effective_dependencies and not missing_dependencies:
                # All prerequisites satisfied — entry agent owns this turn (not intent router).
                agent = AgentRegistry.create(request.agent_config, self)
                logger.info(
                    "workflow_entry_agent_resumed",
                    agent=agent.agent_name,
                    conversation_id=request.conversation_id,
                )

            # Now enforce handoff rules (if any)
            if (
                not executing_prereq_id  # AC #71: Prerequisite execution bypasses handoff blocks
                and request.selected_agent
                and intent.agent_name != request.selected_agent
                and request.agent_config.allowed_handoffs
            ):
                if intent.agent_name not in allowed_agent_names:
                    logger.warning(
                        "handoff_blocked",
                        current=request.selected_agent,
                        target=intent.agent_name,
                        conversation_id=request.conversation_id,
                    )
                    handoff_blocked = True
                    # Stick with the current agent
                    agent = await AgentRegistry.create_by_name(
                        request.selected_agent, request.agent_config, self, db=db, user_id=user_id
                    )
                    # Revert the intent name to match the selected agent's intent
                    if request.current_intent_name:
                        intent = dataclass_replace(
                            _KNOWN_INTENTS[request.current_intent_name], confidence=1.0
                        )

            if handoff_blocked:
                # AC #71: Explicit status and clear refusal when handoff is restricted.
                return ConversationResponse(
                    conversation_id=request.conversation_id,
                    reply=self._make_assistant_message(
                        "I'm sorry, I'm only able to help you with the current topic right now. Is there anything else about that I can assist with?"
                    ),
                    status=ConversationStatus.HANDOFF_BLOCKED,
                    selected_intent=intent.name,
                    selected_agent=agent.agent_name,
                    intent_confidence=intent.confidence,
                    completed_workflow_steps=request.completed_workflow_steps,
                )

            logger.info(
                "agent_selected",
                agent=agent.agent_name,
                conversation_id=request.conversation_id,
            )

            # Use the routed agent's saved config for LLM context (prerequisite steps
            # must not inherit the entry agent's persona).
            active_config = agent.config

            # 3. Select active tool
            active_tool = self._select_active_tool(
                request.messages,
                agent,
                active_tool_id=request.active_tool_id,
                intent=intent,
                current_agent=request.selected_agent or request.agent_config.id,
            )

            # 3b. Extract slots from conversation history.
            # Prefer the user-configured fields on the active DataExtractionTool over
            # the intent's hardcoded required_inputs so custom fields (email, phone,
            # etc.) are actually extracted.
            extraction_inputs = intent.required_inputs
            if (
                active_tool is not None
                and active_tool.type == ToolType.DATA_EXTRACTION
                and isinstance(active_tool.parameters.get("params"), list)
                and active_tool.parameters["params"]
            ):
                extraction_inputs = _normalize_field_key(active_tool.parameters["params"])
                intent = dataclass_replace(intent, required_inputs=extraction_inputs)

            # Pre-slot-extraction scope short-circuit: refuse a clearly off-topic
            # message before any slot-extraction LLM call runs (#168).
            refusal_response = self._scope_refusal(
                message=last_user.content,
                active_config=active_config,
                intent=intent,
                agent=agent,
                conversation_id=request.conversation_id,
                stage="pre_extraction",
            )
            if refusal_response is not None:
                return refusal_response

            slot_result = await self._extract_slots(
                request.messages, extraction_inputs, active_config.llm
            )
            logger.info(
                "slots_extracted",
                filled=list(slot_result.filled.keys()),
                missing=slot_result.missing,
                conversation_id=request.conversation_id,
            )

            # 4. Build system prompt using the routed agent's role
            system_prompt = self._build_system_prompt(
                active_config, active_tool, slot_result, routed_agent=agent
            )

            # 4b. Truncate conversation history if context limit is configured
            truncated_messages = self._truncate_messages(
                request.messages, active_config.context_limit
            )

            # Pre-LLM scope short-circuit: final guard before the LLM call (#168).
            refusal_response = self._scope_refusal(
                message=last_user.content,
                active_config=active_config,
                intent=intent,
                agent=agent,
                conversation_id=request.conversation_id,
                stage="pre_llm",
            )
            if refusal_response is not None:
                return refusal_response

            # 5. Call LLM with a timeout from settings — measure latency
            _llm_start = time.perf_counter()
            llm_text = await asyncio.wait_for(
                self._call_llm(system_prompt, truncated_messages, active_config.llm),
                timeout=self._settings.llm_timeout_seconds,
            )
            _llm_elapsed = time.perf_counter() - _llm_start
            get_metrics().pipeline_latency_seconds.labels(stage="llm_call").observe(_llm_elapsed)

            # 5b. Dispatch active tool when slots are complete.
            dispatch = await self._run_dispatch_step(
                request, active_tool, slot_result, intent, agent, db=db, user_id=user_id
            )
            if dispatch.early_response is not None:
                return dispatch.early_response
            tool_data = dispatch.tool_data
            response_status = dispatch.response_status
            if dispatch.llm_text_override is not None:
                llm_text = dispatch.llm_text_override

            # Advance to the next tool when the current one was dispatched
            updated_completed_steps = list(request.completed_workflow_steps)
            if executing_prereq_id and executing_prereq_id not in updated_completed_steps:
                updated_completed_steps.append(executing_prereq_id)
                logger.info(
                    "workflow_prerequisite_completed",
                    step=executing_prereq_id,
                    conversation_id=request.conversation_id,
                )
            if tool_data and active_tool and not tool_data.get("aborted"):
                if request.agent_config.id not in updated_completed_steps:
                    updated_completed_steps.append(request.agent_config.id)
                    logger.info(
                        "workflow_step_completed",
                        step=request.agent_config.id,
                        conversation_id=request.conversation_id,
                    )

                all_tools = agent.get_task_definitions()
                current_idx = next(
                    (i for i, t in enumerate(all_tools) if t.id == active_tool.id), -1
                )
                next_tool = (
                    all_tools[current_idx + 1] if 0 <= current_idx < len(all_tools) - 1 else None
                )
                next_active_tool_id = next_tool.id if next_tool else None
            else:
                next_active_tool_id = active_tool.id if active_tool else None

            _total_elapsed = time.perf_counter() - _pipeline_start
            get_metrics().pipeline_latency_seconds.labels(stage="total").observe(_total_elapsed)
            logger.info(
                "pipeline_complete",
                conversation_id=request.conversation_id,
                llm_latency_ms=_seconds_to_ms(_llm_elapsed),
                tool_call_latency_ms=_seconds_to_ms(dispatch.tool_call_elapsed),
                total_latency_ms=_seconds_to_ms(_total_elapsed),
            )

            return ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message(llm_text),
                selected_intent=intent.name,
                selected_agent=agent.agent_name,
                intent_confidence=intent.confidence,
                status=response_status,
                extracted_slots=slot_result.to_dict(),
                missing_slots=slot_result.missing,
                tool_invoked=(dispatch.tool_invoked_override or active_tool) if tool_data else None,
                locked_intent_name=intent.name,
                next_active_tool_id=next_active_tool_id,
                completed_workflow_steps=updated_completed_steps,
                latency_ms=_build_pipeline_latency_ms(
                    llm_elapsed=_llm_elapsed,
                    tool_elapsed=dispatch.tool_call_elapsed,
                    total_elapsed=_total_elapsed,
                ),
            )

        # Handler-order note (#197): LLMConfigError and LLMTimeoutError both
        # inherit from LLMError. The subclass handlers must stay BEFORE the
        # LLMError base handler, otherwise config errors would silently
        # downgrade to the generic "llm_provider_error" label and lose their
        # dedicated user message. See test_handler_ordering_regression.
        except LLMConfigError as exc:
            get_metrics().conversation_errors_total.labels(error_type="llm_config").inc()
            logger.error(
                "llm_config_error",
                error=str(exc),
                conversation_id=request.conversation_id,
                hint="Check that the provider API key is set in .env",
            )
            return ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message(
                    "I'm not properly configured to respond right now. Please contact support."
                ),
                status="error",
                error=str(exc),
            )
        except (TimeoutError, LLMTimeoutError) as exc:
            get_metrics().conversation_errors_total.labels(error_type="llm_timeout").inc()
            logger.warning(
                "llm_timeout",
                error=str(exc),
                conversation_id=request.conversation_id,
            )
            return ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message(
                    "I'm sorry, I'm having trouble connecting to my brain right now. Please try again."
                ),
                status="error",
                error=f"LLM call timed out after {self._settings.llm_timeout_seconds} seconds.",
            )
        except LLMError as exc:
            # Provider failures (auth, quota/rate-limit, API outage) surfaced by the
            # intent router and LLM call sites (#197). Distinct label + message so a
            # real outage is never mistaken for a clarification or generic error.
            get_metrics().conversation_errors_total.labels(error_type="llm_provider_error").inc()
            logger.error(
                "llm_provider_error",
                error=str(exc),
                conversation_id=request.conversation_id,
                hint="Check provider status, API key validity, and remaining quota.",
            )
            return ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message(
                    "I'm having trouble reaching my language model provider right now. "
                    "Please try again in a moment."
                ),
                status="error",
                error=str(exc),
            )
        except UnicodeEncodeError as exc:
            get_metrics().conversation_errors_total.labels(error_type="encoding_error").inc()
            logger.error(
                "encoding_error",
                error=str(exc),
                conversation_id=request.conversation_id,
                exc_info=True,
            )
            return ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message("An unexpected error occurred."),
                status="error",
                error=str(exc),
            )
        except ValueError as exc:
            get_metrics().conversation_errors_total.labels(error_type="invalid_input").inc()
            logger.warning(
                "invalid_runtime_input", error=str(exc), conversation_id=request.conversation_id
            )
            return ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message("I encountered an error. Please try again."),
                status="error",
                error=str(exc),
            )
        except Exception as exc:
            get_metrics().conversation_errors_total.labels(error_type="runtime_error").inc()
            logger.error(
                "runtime_error",
                error=str(exc),
                conversation_id=request.conversation_id,
                exc_info=True,
            )
            return ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message("An unexpected error occurred."),
                status="error",
                error=str(exc),
            )

    async def process_message_stream(
        self,
        request: ConversationRequest,
        db: AsyncSession | None = None,
        user_id: int | None = None,
    ):
        """Streaming variant of process_message; yields str chunks then ConversationResponse."""
        _pipeline_start = time.perf_counter()
        try:
            # 0a. Manual transfer short-circuit.
            if request.manual_transfer and (
                request.manual_transfer.target_agent_id or request.manual_transfer.target_agent_name
            ):
                yield await self._handle_manual_transfer(request, db, user_id=user_id)
                return

            if db is not None and user_id is not None:
                from taskorbit.database.crud import enrich_request_dependency_configs

                request = await enrich_request_dependency_configs(request, db, user_id)

            effective_selected = _effective_selected_agent(request.selected_agent)
            if effective_selected != request.selected_agent:
                request = request.model_copy(update={"selected_agent": effective_selected})

            last_user = next(
                (m for m in reversed(request.messages) if m.role == MessageRole.USER),
                None,
            )
            if not last_user or not last_user.content.strip():
                raise ValueError("No user message content found in request.")

            # 0. User-initiated end-call.
            from taskorbit.types import ConversationStatus, ToolType

            end_call_tool = next(
                (t for t in request.agent_config.tools if t.type == ToolType.END_CALL),
                None,
            )
            logger.debug(
                "end_call_check",
                conversation_id=request.conversation_id,
                tool_found=end_call_tool is not None,
                tools_count=len(request.agent_config.tools),
                tool_types=[t.type for t in request.agent_config.tools],
                user_requested=self._user_requested_end_call(last_user.content),
            )
            if end_call_tool and self._user_requested_end_call(last_user.content):
                try:
                    farewell = await asyncio.wait_for(
                        self._call_llm(
                            f"You are {request.agent_config.name}. "
                            f"Persona: {request.agent_config.persona}\n"
                            "The user wants to end the conversation. "
                            "Say a brief, warm farewell in one sentence.",
                            request.messages,
                            request.agent_config.llm,
                        ),
                        timeout=self._settings.llm_timeout_seconds,
                    )
                except Exception:  # noqa: BLE001
                    farewell = "Goodbye! Take care."
                    logger.warning(
                        "end_call_farewell_llm_failed",
                        conversation_id=request.conversation_id,
                        fallback=farewell,
                    )
                _, tool_elapsed = await self._dispatch_tool(end_call_tool, {})
                logger.info(
                    "end_call_user_initiated",
                    conversation_id=request.conversation_id,
                    tool_call_latency_ms=_seconds_to_ms(tool_elapsed),
                )
                yield ConversationResponse(
                    conversation_id=request.conversation_id,
                    reply=self._make_assistant_message(farewell),
                    status=ConversationStatus.ENDED,
                    selected_intent="",
                    selected_agent="",
                    tool_invoked=end_call_tool,
                    latency_ms=_build_pipeline_latency_ms(tool_elapsed=tool_elapsed),
                )
                return

            # 0b. Pre-intent scope short-circuit (parity with text path, #168 follow-up).
            refusal_response = self._entry_scope_refusal(
                message=last_user.content,
                request=request,
                stage="pre_intent",
            )
            if refusal_response is not None:
                yield refusal_response
                return

            # 1. Detect intent.
            if request.current_intent_name and request.current_intent_name in _KNOWN_INTENTS:
                fresh = await self._intent_router.detect(
                    last_user.content,
                    request.messages,
                    self._call_llm_json,
                    request.agent_config.llm,
                )
                if (
                    fresh.name != request.current_intent_name
                    and fresh.confidence >= self._intent_router._threshold
                    and not fresh.requires_clarification
                ):
                    intent = fresh
                    logger.info(
                        "intent_lock_broken",
                        old=request.current_intent_name,
                        new=intent.name,
                        confidence=intent.confidence,
                        conversation_id=request.conversation_id,
                    )
                else:
                    intent = dataclass_replace(
                        _KNOWN_INTENTS[request.current_intent_name], confidence=1.0
                    )
                    logger.info(
                        "intent_locked",
                        intent=intent.name,
                        conversation_id=request.conversation_id,
                    )
            else:
                intent = await self._intent_router.detect(
                    last_user.content,
                    request.messages,
                    self._call_llm_json,
                    request.agent_config.llm,
                )
                logger.info(
                    "intent_detected",
                    intent=intent.name,
                    confidence=intent.confidence,
                    conversation_id=request.conversation_id,
                )

            intent = _resolve_intent_after_clarification_gate(request, intent)

            if intent.requires_clarification:
                from taskorbit.intent import _CLARIFICATION_REPLY

                yield ConversationResponse(
                    conversation_id=request.conversation_id,
                    reply=self._make_assistant_message(_CLARIFICATION_REPLY),
                    status=ConversationStatus.CLARIFICATION,
                    selected_intent=intent.name,
                    selected_agent="",
                    intent_confidence=intent.confidence,
                )
                return

            # 2. Select agent.
            handoff_blocked = False
            allowed_agent_names: list[str] = []
            if not request.selected_agent:
                agent = AgentRegistry.create(request.agent_config, self)
                logger.info(
                    "entry_agent_locked",
                    agent=agent.agent_name,
                    conversation_id=request.conversation_id,
                )
            else:
                agent = await AgentRegistry.create_by_name(
                    intent.agent_name, request.agent_config, self, db=db, user_id=user_id
                )
                allowed_agent_names = []
                if (
                    intent.agent_name != request.selected_agent
                    and request.agent_config.allowed_handoffs
                ):
                    allowed_agent_names = [
                        AgentRegistry.get_agent_name_for_id(cfg_id)
                        for cfg_id in request.agent_config.allowed_handoffs
                    ]

            # Resolve workflow dependencies BEFORE enforcing handoff rules.
            # See the equivalent block in process_message for why this cannot
            # reuse the result computed inside the clarification gate: the gate
            # may return a different intent (from _KNOWN_INTENTS), so the two
            # calls can operate on different intents and must stay separate.
            direct_dependencies, effective_dependencies, missing_dependencies = (
                _resolve_missing_dependencies(request, intent)
            )

            logger.debug(
                "workflow_dependency_check",
                direct=direct_dependencies,
                effective=effective_dependencies,
                completed=request.completed_workflow_steps,
                missing=missing_dependencies,
                selected=request.selected_agent,
            )

            executing_prereq_id: str | None = None
            if missing_dependencies:
                next_dep = missing_dependencies[0]
                executing_prereq = _selected_agent_matches_dep(request.selected_agent, next_dep)

                if executing_prereq:
                    executing_prereq_id = next_dep
                    dep_config = request.dependency_configs.get(next_dep)
                    if not dep_config:
                        logger.error(
                            "workflow_dependency_config_missing",
                            dependency=next_dep,
                            conversation_id=request.conversation_id,
                        )
                        handoff_blocked = True
                        agent = AgentRegistry.create(request.agent_config, self)
                    else:
                        agent = AgentRegistry.create(dep_config, self)
                        logger.info(
                            "workflow_dependency_executing",
                            dependency=next_dep,
                            agent=agent.agent_name,
                            conversation_id=request.conversation_id,
                        )
                else:
                    logger.info(
                        "workflow_dependency_missing",
                        dependency=next_dep,
                        conversation_id=request.conversation_id,
                    )

                    is_decision_for_this_workflow = (
                        request.confirmation_id == f"workflow_{next_dep}"
                    )
                    has_decision = is_decision_for_this_workflow and request.decision is not None

                    if not has_decision:
                        dep_name = next_dep.replace("-", " ")
                        dep_config = request.dependency_configs.get(next_dep)
                        if dep_config:
                            dep_name = dep_config.name

                        yield ConversationResponse(
                            conversation_id=request.conversation_id,
                            reply=self._make_assistant_message(
                                _workflow_prereq_confirmation_message(
                                    request.agent_config.name, dep_name
                                )
                            ),
                            status=ConversationStatus.WORKFLOW_CONFIRMATION_REQUIRED,
                            confirmation=ConfirmationResponsePayload(
                                confirmation_id=f"workflow_{next_dep}",
                                action=f"Start {next_dep} workflow",
                                description=f"Prerequisite: {dep_name}",
                            ),
                            selected_intent=intent.name,
                            selected_agent=_workflow_ui_selected_agent(request) or "",
                            intent_confidence=intent.confidence,
                            locked_intent_name=intent.name,
                            completed_workflow_steps=request.completed_workflow_steps,
                        )
                        return

                    if request.decision == "reject":
                        logger.info(
                            "workflow_dependency_rejected",
                            dependency=next_dep,
                            conversation_id=request.conversation_id,
                        )
                        yield ConversationResponse(
                            conversation_id=request.conversation_id,
                            reply=self._make_assistant_message(
                                "Understood. I can't proceed without those prerequisite steps. Is there anything else I can help you with?"
                            ),
                            status=ConversationStatus.REJECTED,
                            selected_intent=intent.name,
                            selected_agent=_workflow_ui_selected_agent(request) or "",
                            locked_intent_name=intent.name,
                            completed_workflow_steps=request.completed_workflow_steps,
                        )
                        return

                    logger.info(
                        "workflow_dependency_confirmed",
                        dependency=next_dep,
                        conversation_id=request.conversation_id,
                    )
                    yield ConversationResponse(
                        conversation_id=request.conversation_id,
                        reply=self._make_assistant_message(_workflow_prereq_start_ack(next_dep)),
                        status=ConversationStatus.SUCCESS,
                        selected_agent=next_dep,
                        selected_intent=intent.name,
                        intent_confidence=1.0,
                        locked_intent_name=intent.name,
                        completed_workflow_steps=request.completed_workflow_steps,
                    )
                    return

            elif effective_dependencies and not missing_dependencies:
                agent = AgentRegistry.create(request.agent_config, self)
                logger.info(
                    "workflow_entry_agent_resumed",
                    agent=agent.agent_name,
                    conversation_id=request.conversation_id,
                )

            # Enforce handoff rules.
            if (
                not executing_prereq_id
                and request.selected_agent
                and intent.agent_name != request.selected_agent
                and request.agent_config.allowed_handoffs
            ):
                if intent.agent_name not in allowed_agent_names:
                    logger.warning(
                        "handoff_blocked",
                        current=request.selected_agent,
                        target=intent.agent_name,
                        conversation_id=request.conversation_id,
                    )
                    handoff_blocked = True
                    agent = await AgentRegistry.create_by_name(
                        request.selected_agent,
                        request.agent_config,
                        self,
                        db=db,
                        user_id=user_id,
                    )
                    if request.current_intent_name:
                        intent = dataclass_replace(
                            _KNOWN_INTENTS[request.current_intent_name], confidence=1.0
                        )

            if handoff_blocked:
                yield ConversationResponse(
                    conversation_id=request.conversation_id,
                    reply=self._make_assistant_message(
                        "I'm sorry, I'm only able to help you with the current topic right now. Is there anything else about that I can assist with?"
                    ),
                    status=ConversationStatus.HANDOFF_BLOCKED,
                    selected_intent=intent.name,
                    selected_agent=agent.agent_name,
                    intent_confidence=intent.confidence,
                    completed_workflow_steps=request.completed_workflow_steps,
                )
                return

            logger.info(
                "agent_selected",
                agent=agent.agent_name,
                conversation_id=request.conversation_id,
            )

            active_config = agent.config

            # 3. Select active tool.
            active_tool = self._select_active_tool(
                request.messages,
                agent,
                active_tool_id=request.active_tool_id,
                intent=intent,
                current_agent=request.selected_agent or request.agent_config.id,
            )

            # Pre-extraction scope short-circuit (parity with the text path, #168):
            # refuse a clearly off-topic message before any slot-extraction LLM
            # call or tool dispatch runs. Without this, an off-topic voice turn
            # could fire a tool before being refused.
            refusal_response = self._scope_refusal(
                message=last_user.content,
                active_config=active_config,
                intent=intent,
                agent=agent,
                conversation_id=request.conversation_id,
                stage="pre_extraction",
            )
            if refusal_response is not None:
                yield refusal_response
                return

            # 3b. Extract slots.
            # Prefer the user-configured fields on the active DataExtractionTool over
            # the intent's hardcoded required_inputs so custom fields (email, phone,
            # etc.) are actually extracted.
            extraction_inputs = intent.required_inputs
            if (
                active_tool is not None
                and active_tool.type == ToolType.DATA_EXTRACTION
                and isinstance(active_tool.parameters.get("params"), list)
                and active_tool.parameters["params"]
            ):
                extraction_inputs = _normalize_field_key(active_tool.parameters["params"])
                intent = dataclass_replace(intent, required_inputs=extraction_inputs)

            slot_result = await self._extract_slots(
                request.messages, extraction_inputs, active_config.llm
            )
            logger.info(
                "slots_extracted",
                filled=list(slot_result.filled.keys()),
                missing=slot_result.missing,
                conversation_id=request.conversation_id,
            )

            # 4. Build system prompt.
            system_prompt = self._build_system_prompt(
                active_config, active_tool, slot_result, routed_agent=agent
            )

            # 4b. Truncate messages.
            truncated_messages = self._truncate_messages(
                request.messages, active_config.context_limit
            )

            # 5b. Run dispatch logic before streaming so confirmation short-circuits
            # before any tokens are sent to the client.
            dispatch = await self._run_dispatch_step(
                request, active_tool, slot_result, intent, agent, db=db, user_id=user_id
            )
            if dispatch.early_response is not None:
                yield dispatch.early_response
                return

            # Pre-LLM scope short-circuit: final guard before streaming tokens (#168).
            refusal_response = self._scope_refusal(
                message=last_user.content,
                active_config=active_config,
                intent=intent,
                agent=agent,
                conversation_id=request.conversation_id,
                stage="pre_llm",
            )
            if refusal_response is not None:
                yield refusal_response
                return

            # 5. Stream LLM response or use rejection override.
            _llm_start = time.perf_counter()
            full_text_parts: list[str] = []
            if dispatch.llm_text_override is not None:
                full_text_parts = [dispatch.llm_text_override]
            else:
                async for chunk in self._call_llm_stream(
                    system_prompt, truncated_messages, active_config.llm
                ):
                    full_text_parts.append(chunk)
                    yield chunk
            _llm_elapsed = time.perf_counter() - _llm_start
            get_metrics().pipeline_latency_seconds.labels(stage="llm_call").observe(_llm_elapsed)

            llm_text = "".join(full_text_parts)
            tool_data = dispatch.tool_data
            response_status = dispatch.response_status

            # Advance workflow steps.
            updated_completed_steps = list(request.completed_workflow_steps)
            if executing_prereq_id and executing_prereq_id not in updated_completed_steps:
                updated_completed_steps.append(executing_prereq_id)
                logger.info(
                    "workflow_prerequisite_completed",
                    step=executing_prereq_id,
                    conversation_id=request.conversation_id,
                )
            if tool_data and active_tool and not tool_data.get("aborted"):
                if request.agent_config.id not in updated_completed_steps:
                    updated_completed_steps.append(request.agent_config.id)
                    logger.info(
                        "workflow_step_completed",
                        step=request.agent_config.id,
                        conversation_id=request.conversation_id,
                    )

                all_tools = agent.get_task_definitions()
                current_idx = next(
                    (i for i, t in enumerate(all_tools) if t.id == active_tool.id), -1
                )
                next_tool = (
                    all_tools[current_idx + 1] if 0 <= current_idx < len(all_tools) - 1 else None
                )
                next_active_tool_id = next_tool.id if next_tool else None
            else:
                next_active_tool_id = active_tool.id if active_tool else None

            _total_elapsed = time.perf_counter() - _pipeline_start
            get_metrics().pipeline_latency_seconds.labels(stage="total").observe(_total_elapsed)
            logger.info(
                "pipeline_complete",
                conversation_id=request.conversation_id,
                llm_latency_ms=_seconds_to_ms(_llm_elapsed),
                tool_call_latency_ms=_seconds_to_ms(dispatch.tool_call_elapsed),
                total_latency_ms=_seconds_to_ms(_total_elapsed),
            )

            yield ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message(llm_text),
                selected_intent=intent.name,
                selected_agent=agent.agent_name,
                intent_confidence=intent.confidence,
                status=response_status,
                extracted_slots=slot_result.to_dict(),
                missing_slots=slot_result.missing,
                tool_invoked=(dispatch.tool_invoked_override or active_tool) if tool_data else None,
                locked_intent_name=intent.name,
                next_active_tool_id=next_active_tool_id,
                completed_workflow_steps=updated_completed_steps,
                latency_ms=_build_pipeline_latency_ms(
                    llm_elapsed=_llm_elapsed,
                    tool_elapsed=dispatch.tool_call_elapsed,
                    total_elapsed=_total_elapsed,
                ),
            )

        # Handler-order note (#197): LLMConfigError and LLMTimeoutError both
        # inherit from LLMError. The subclass handlers must stay BEFORE the
        # LLMError base handler, otherwise config errors would silently
        # downgrade to the generic "llm_provider_error" label and lose their
        # dedicated user message. See test_handler_ordering_regression.
        except LLMConfigError as exc:
            get_metrics().conversation_errors_total.labels(error_type="llm_config").inc()
            logger.error(
                "llm_config_error",
                error=str(exc),
                conversation_id=request.conversation_id,
                hint="Check that the provider API key is set in .env",
            )
            yield ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message(
                    "I'm not properly configured to respond right now. Please contact support."
                ),
                status="error",
                error=str(exc),
            )
        except (TimeoutError, LLMTimeoutError) as exc:
            get_metrics().conversation_errors_total.labels(error_type="llm_timeout").inc()
            logger.warning(
                "llm_timeout",
                error=str(exc),
                conversation_id=request.conversation_id,
            )
            yield ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message(
                    "I'm sorry, I'm having trouble connecting to my brain right now. Please try again."
                ),
                status="error",
                error=f"LLM call timed out after {self._settings.llm_timeout_seconds} seconds.",
            )
        except LLMError as exc:
            # Provider failures (auth, quota/rate-limit, API outage) surfaced by the
            # intent router and LLM call sites (#197) — mirror of process_message.
            get_metrics().conversation_errors_total.labels(error_type="llm_provider_error").inc()
            logger.error(
                "llm_provider_error",
                error=str(exc),
                conversation_id=request.conversation_id,
                hint="Check provider status, API key validity, and remaining quota.",
            )
            yield ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message(
                    "I'm having trouble reaching my language model provider right now. "
                    "Please try again in a moment."
                ),
                status="error",
                error=str(exc),
            )
        except UnicodeEncodeError as exc:
            get_metrics().conversation_errors_total.labels(error_type="encoding_error").inc()
            logger.error(
                "encoding_error",
                error=str(exc),
                conversation_id=request.conversation_id,
                exc_info=True,
            )
            yield ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message("An unexpected error occurred."),
                status="error",
                error=str(exc),
            )
        except ValueError as exc:
            get_metrics().conversation_errors_total.labels(error_type="invalid_input").inc()
            logger.warning(
                "invalid_runtime_input", error=str(exc), conversation_id=request.conversation_id
            )
            yield ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message("I encountered an error. Please try again."),
                status="error",
                error=str(exc),
            )
        except Exception as exc:
            get_metrics().conversation_errors_total.labels(error_type="runtime_error").inc()
            logger.error(
                "runtime_error",
                error=str(exc),
                conversation_id=request.conversation_id,
                exc_info=True,
            )
            yield ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message("An unexpected error occurred."),
                status="error",
                error=str(exc),
            )

    async def _handle_manual_transfer(
        self,
        request: ConversationRequest,
        db: AsyncSession | None,
        user_id: int | None = None,
    ) -> ConversationResponse:
        """Handle a UI-initiated transfer to a specific agent by ID or name.

        Resolves the target AgentConfiguration from the DB, swaps the config on
        the request, clears the manual_transfer field to avoid recursion, then
        re-enters the normal pipeline so intent detection, slot extraction, and
        the LLM call all run under the new agent's persona and tools.
        """
        from taskorbit.database.crud import (
            get_agent_configuration_by_id,
            get_agent_configuration_by_name,
            get_default_agent_template,
        )
        from taskorbit.types import ConversationStatus

        mt = request.manual_transfer
        target_id = mt.target_agent_id if mt else None

        # Resolve by name when only a name was given — scope to caller's user_id
        # so one user can never be routed to another user's agent config.
        if not target_id and mt and mt.target_agent_name and db is not None:
            record = await get_agent_configuration_by_name(
                db, mt.target_agent_name, user_id=user_id
            )
            if record:
                target_id = record.id

        if not target_id:
            logger.warning(
                "manual_transfer_agent_not_found",
                target_id=mt.target_agent_id if mt else None,
                target_name=mt.target_agent_name if mt else None,
                conversation_id=request.conversation_id,
            )
            return ConversationResponse(
                conversation_id=request.conversation_id or "",
                reply=self._make_assistant_message(
                    "I couldn't find the requested agent. Please try again."
                ),
                status=ConversationStatus.ERROR,
                error="manual_transfer_agent_not_found",
            )

        # Load target config — try user's copy first, then built-in template.
        # Built-in (un-customized) agents live in default_agent_templates, not
        # agent_configurations, so we need both lookups to cover all dropdown entries.
        config_dict: dict | None = None
        if db is not None:
            record = await get_agent_configuration_by_id(db, target_id)
            if record is not None:
                config_dict = record.config
            else:
                template = await get_default_agent_template(db, target_id)
                if template is not None:
                    config_dict = template.config

        if config_dict is None:
            logger.warning(
                "manual_transfer_agent_config_missing",
                target_id=target_id,
                conversation_id=request.conversation_id,
            )
            return ConversationResponse(
                conversation_id=request.conversation_id or "",
                reply=self._make_assistant_message(
                    "I couldn't load the requested agent's configuration."
                ),
                status=ConversationStatus.ERROR,
                error="manual_transfer_agent_config_missing",
            )

        try:
            target_config = AgentConfig(**config_dict)
        except Exception as exc:
            logger.error(
                "manual_transfer_invalid_config",
                target_id=target_id,
                error=str(exc),
                conversation_id=request.conversation_id,
            )
            return ConversationResponse(
                conversation_id=request.conversation_id or "",
                reply=self._make_assistant_message(
                    "The requested agent has an invalid configuration."
                ),
                status=ConversationStatus.ERROR,
                error=str(exc),
            )

        logger.info(
            "manual_transfer_executing",
            from_agent=request.agent_config.id,
            to_agent=target_id,
            conversation_id=request.conversation_id,
        )

        # Re-enter the pipeline with the new agent config; full history is preserved.
        updated_request = request.model_copy(
            update={"agent_config": target_config, "manual_transfer": None}
        )
        return await self.process_message(updated_request, db, user_id=user_id)

    def _entry_scope_refusal(
        self,
        *,
        message: str,
        request: ConversationRequest,
        stage: str = "pre_intent",
    ) -> ConversationResponse | None:
        """Refuse using the entry agent's constraints before intent routing."""
        if not request.agent_config.persona_constraints:
            return None
        entry_agent = AgentRegistry.create(request.agent_config, self)
        placeholder = IntentResult(
            name="",
            description="",
            agent_name=entry_agent.agent_name,
            confidence=0.0,
        )
        return self._scope_refusal(
            message=message,
            active_config=request.agent_config,
            intent=placeholder,
            agent=entry_agent,
            conversation_id=request.conversation_id,
            stage=stage,
        )

    def _scope_refusal(
        self,
        *,
        message: str,
        active_config: AgentConfig,
        intent: IntentResult,
        agent: Any,
        conversation_id: str,
        stage: str,
    ) -> ConversationResponse | None:
        """Refuse a clearly out-of-scope message, or return ``None`` to proceed.

        Single source of truth for the guardrail short-circuit so the text and
        voice/stream paths enforce identically (#168). Gated by
        ``enable_scope_shortcircuit``; fail-open -- a classifier error allows the
        turn through rather than hard-failing a live call. ``stage`` labels the
        call site in logs ("pre_intent" / "pre_extraction" / "pre_llm").
        """
        if not self._settings.enable_scope_shortcircuit:
            return None
        try:
            in_scope, match = is_message_in_scope(message, active_config.persona_constraints)
        except Exception as exc:  # noqa: BLE001 - never fail a turn on a classifier error
            logger.exception(
                "scope_check_failed",
                conversation_id=conversation_id,
                stage=stage,
                error=str(exc),
            )
            return None
        if in_scope:
            return None
        refusal = (
            active_config.persona_constraints.refusal_template
            if active_config.persona_constraints
            and active_config.persona_constraints.refusal_template
            else "I'm sorry, I can't assist with that topic."
        )
        logger.info(
            "message_out_of_scope",
            conversation_id=conversation_id,
            stage=stage,
            match=match,
        )
        return ConversationResponse(
            conversation_id=conversation_id,
            reply=self._make_assistant_message(refusal),
            status=ConversationStatus.REJECTED,
            selected_intent=intent.name,
            selected_agent=agent.agent_name,
            intent_confidence=intent.confidence,
        )

    def _build_system_prompt(
        self,
        agent_config: AgentConfig,
        active_tool: ToolDefinition | None,
        slot_result: Any | None = None,
        routed_agent: Any | None = None,
    ) -> str:
        """Construct a system prompt (LLM context) for the current task."""
        from taskorbit.integrations.llm.prompts import with_persona_guardrails

        lines = [
            f"You are {agent_config.name}.",
            f"Persona: {agent_config.persona}",
            # Replies are spoken aloud in the voice path, so keep them short: a
            # long monologue is slow to hear and hard to interrupt (#153). One
            # or two short sentences, asking for at most one missing detail at a
            # time.
            "Keep replies brief and conversational, at most two short sentences. "
            "Ask for at most one missing detail at a time.",
        ]
        if routed_agent is not None and routed_agent.agent_name != "base":
            lines.append(
                f"Role: You are currently acting as the {routed_agent.agent_name.replace('_', ' ')} specialist."
            )
        if active_tool:
            lines.append(f"Current task: {active_tool.name} - {active_tool.description}")
            if active_tool.parameters:
                lines.append(f"Available parameters: {active_tool.parameters}")
        if slot_result is not None:
            if slot_result.filled:
                lines.append(
                    "CONFIRMED CUSTOMER DATA — already collected, do NOT ask for these again:"
                )
                for name, sv in slot_result.filled.items():
                    label = name.replace("_", " ").title()
                    lines.append(f"  - {label}: {sv.value}")
                lines.append(
                    "When the user asks about any confirmed data above, "
                    "answer directly from this list without asking them to provide it again."
                )
            if slot_result.missing:
                missing_labels = [m.replace("_", " ").title() for m in slot_result.missing]
                lines.append(f"Still need to collect: {', '.join(missing_labels)}")
        prompt = "\n".join(lines)
        prompt = with_persona_guardrails(prompt, agent_config.persona_constraints)
        if agent_config.persona_constraints is not None:
            logger.info(
                "persona_guardrails_applied",
                scope_set=bool(agent_config.persona_constraints.scope),
                out_of_scope_count=len(agent_config.persona_constraints.out_of_scope),
                refusal_template_set=bool(agent_config.persona_constraints.refusal_template),
            )
        return prompt

    def _truncate_messages(
        self,
        messages: list[Message],
        context_limit: ContextLimitConfig | None,
    ) -> list[Message]:
        """Cap conversation history at ``context_limit.value`` non-system messages."""
        if context_limit is None:
            return messages

        system_msgs = [m for m in messages if m.role == MessageRole.SYSTEM]
        other_msgs = [m for m in messages if m.role != MessageRole.SYSTEM]

        limit = context_limit.value
        if len(other_msgs) <= limit:
            return messages

        trimmed_other = other_msgs[-limit:]
        logger.info(
            "message_truncation_applied",
            original_count=len(other_msgs),
            trimmed_count=len(trimmed_other),
            dropped_count=len(other_msgs) - len(trimmed_other),
            system_msgs_protected=len(system_msgs),
        )
        return system_msgs + trimmed_other

    async def _extract_slots(
        self,
        messages: list[Message],
        required_inputs: list[dict[str, Any]],
        llm_config: LLMConfig,
    ) -> Any:
        """Run slot extraction over the conversation history."""
        from taskorbit.slots import SlotExtractionResult, SlotExtractor

        if not required_inputs:
            return SlotExtractionResult()
        try:
            extractor = SlotExtractor(llm_fn=self._call_llm_json, llm_config=llm_config)
            return await extractor.extract(messages, required_inputs)
        except LLMError:
            # Provider failures must surface (#197) — treating them as "all slots
            # missing" would make the agent re-ask for data the user already gave.
            raise
        except Exception as exc:
            logger.warning(
                "slot_extraction_error",
                error=str(exc),
            )
            missing = [
                f.get("name") or f.get("variable_name", "unknown")
                for f in required_inputs
                if f.get("required", True)
            ]
            return SlotExtractionResult(missing=missing)

    def _select_active_tool(
        self,
        messages: list[Message],
        agent: BaseAgent,
        active_tool_id: str | None = None,
        intent: IntentResult | None = None,
        current_agent: str | None = None,
    ) -> ToolDefinition | None:
        """Decide which tool should be in scope for this turn, if any.

        Order: an explicit active_tool_id pin (confirmation round-trips) wins;
        then, when intent routing points AWAY from the current agent and the
        config carries an agent_transfer tool for that destination, the
        transfer owns the turn (#212 — multi-tool configs otherwise never
        reach tools[1:], because neither client round-trips
        next_active_tool_id); otherwise the first configured tool.
        """
        tools = agent.get_task_definitions()
        if not tools:
            return None
        if active_tool_id:
            match = next((t for t in tools if t.id == active_tool_id), None)
            if match:
                return match

        if intent is not None and intent.agent_name:
            from taskorbit.tools.agent_transfer import resolve_builtin_transfer_target

            # current_agent can arrive as a template slug after a completed voice
            # handoff ("technical-support-agent"), while intent.agent_name is a
            # registry name ("technical_support"). Normalise before comparing so
            # a finished handoff never re-fires the transfer (#212).
            effective_current = (
                resolve_builtin_transfer_target(current_agent) or current_agent
                if current_agent
                else current_agent
            )
            if intent.agent_name == effective_current:
                return tools[0]
            for tool in tools:
                if tool.type != ToolType.AGENT_TRANSFER:
                    continue
                targets = tool.parameters.get("targets") or []
                for raw in targets:
                    if resolve_builtin_transfer_target(str(raw)) == intent.agent_name:
                        logger.info(
                            "agent_transfer_tool_selected",
                            destination=intent.agent_name,
                            requested_target=str(raw),
                            tool_id=tool.id,
                        )
                        return tool

        return tools[0]

    async def _call_llm(
        self,
        system_prompt: str,
        messages: list[Message],
        llm_config: LLMConfig,
    ) -> str:
        """Call the LLM provider specified by ``llm_config`` and return its text."""
        from taskorbit.integrations.llm.factory import get_llm_client
        from taskorbit.integrations.llm.prompts import with_same_language_instruction

        augmented_prompt = with_same_language_instruction(system_prompt)
        client = get_llm_client(llm_config, settings=self._settings)
        return await client.generate(augmented_prompt, messages, llm_config)

    async def _call_llm_json(
        self,
        system_prompt: str,
        messages: list[Message],
        llm_config: LLMConfig,
    ) -> str:
        """Call the LLM and return its text WITHOUT the same-language instruction.

        Use this for structured JSON calls (intent classification, slot extraction)
        where the language instruction conflicts with 'Respond ONLY with valid JSON'
        and causes models like Gemini to produce natural-language output instead.
        """
        from taskorbit.integrations.llm.factory import get_llm_client

        client = get_llm_client(llm_config, settings=self._settings)
        return await client.generate(system_prompt, messages, llm_config)

    async def _call_llm_stream(
        self,
        system_prompt: str,
        messages: list[Message],
        llm_config: LLMConfig,
    ):
        """Stream LLM response tokens from the configured provider."""
        from taskorbit.integrations.llm.factory import get_llm_client
        from taskorbit.integrations.llm.prompts import with_same_language_instruction

        augmented_prompt = with_same_language_instruction(system_prompt)
        client = get_llm_client(llm_config, settings=self._settings)
        async for chunk in client.generate_stream(augmented_prompt, messages, llm_config):
            yield chunk

    async def _run_dispatch_step(
        self,
        request: ConversationRequest,
        active_tool: ToolDefinition | None,
        slot_result: Any,
        intent: Any,
        agent: Any,
        db: AsyncSession | None = None,
        user_id: int | None = None,
    ) -> _DispatchResult:
        """Run the tool dispatch logic (step 5b) shared by streaming and non-streaming paths."""
        tool_data: dict[str, Any] = {}
        response_status = ConversationStatus.SUCCESS
        llm_text_override: str | None = None
        tool_call_elapsed: float | None = None
        tool_invoked_override: ToolDefinition | None = None

        no_slots_tool_ready = active_tool is not None and active_tool.type in (
            ToolType.END_CALL,
            ToolType.AGENT_TRANSFER,
        )
        slots_ready = (
            active_tool is not None and slot_result.is_complete and bool(intent.required_inputs)
        )

        if no_slots_tool_ready or slots_ready:
            is_decision_for_this_tool = request.confirmation_id == active_tool.id
            has_decision = is_decision_for_this_tool and request.decision is not None

            if active_tool.confirmation.required and not has_decision:
                logger.info(
                    "confirmation_required",
                    tool_id=active_tool.id,
                    conversation_id=request.conversation_id,
                )
                return _DispatchResult(
                    early_response=ConversationResponse(
                        conversation_id=request.conversation_id,
                        reply=self._make_assistant_message(
                            active_tool.confirmation.prompt
                            or f"I need your confirmation before I proceed with {active_tool.name}. Should I go ahead?"
                        ),
                        status=ConversationStatus.CONFIRMATION_REQUIRED,
                        tool_invoked=active_tool,
                        confirmation=ConfirmationResponsePayload(
                            confirmation_id=active_tool.id,
                            action=active_tool.name,
                            description=active_tool.confirmation.prompt
                            or f"Execute {active_tool.name}",
                        ),
                        selected_intent=intent.name,
                        selected_agent=agent.agent_name,
                        intent_confidence=intent.confidence,
                        extracted_slots=slot_result.to_dict(),
                        missing_slots=slot_result.missing,
                        locked_intent_name=intent.name,
                        next_active_tool_id=active_tool.id,
                        completed_workflow_steps=request.completed_workflow_steps,
                    ),
                    tool_data={},
                    response_status=ConversationStatus.CONFIRMATION_REQUIRED,
                    llm_text_override=None,
                )

            if has_decision and request.decision == "reject":
                logger.info(
                    "tool_execution_rejected",
                    tool_id=active_tool.id,
                    conversation_id=request.conversation_id,
                )
                response_status = ConversationStatus.REJECTED
                tool_data = {"aborted": True}
                llm_text_override = (
                    "Understood. I've cancelled that action. How else can I help you?"
                )
            else:
                dispatch_context: dict[str, Any] = dict(slot_result.to_dict())
                if active_tool.type == ToolType.AGENT_TRANSFER:
                    from taskorbit.tools.agent_transfer import (
                        resolve_builtin_transfer_target,
                        resolve_transfer_target,
                    )

                    targets = active_tool.parameters.get("targets") or []
                    if targets:
                        raw = str(targets[0])
                        # Multi-target tools: prefer the target matching the
                        # routed intent so selection and dispatch agree (#212).
                        if intent is not None and len(targets) > 1:
                            for candidate in targets:
                                if (
                                    resolve_builtin_transfer_target(str(candidate))
                                    == intent.agent_name
                                ):
                                    raw = str(candidate)
                                    break
                        resolved_target = await resolve_transfer_target(raw, db=db, user_id=user_id)
                        if resolved_target is not None:
                            dispatch_context["target_agent_id"] = resolved_target.canonical_id
                        else:
                            # Pass the raw value through; the tool re-resolves and
                            # owns the user-facing "Unknown agent" error (#212).
                            logger.warning(
                                "agent_transfer_target_unresolved",
                                raw_target=raw,
                                conversation_id=request.conversation_id,
                            )
                            dispatch_context["target_agent_id"] = raw
                    dispatch_context["conversation_history"] = [
                        {"role": m.role.value, "content": m.content} for m in request.messages
                    ]
                elif active_tool.type == ToolType.EXTERNAL_API:
                    dispatch_context = {
                        **active_tool.parameters,
                        "args": dict(slot_result.to_dict()),
                    }
                tool_data, tool_call_elapsed = await self._dispatch_tool(
                    active_tool, dispatch_context, db=db, user_id=user_id
                )
                logger.info(
                    "tool_dispatch_complete",
                    tool_type=active_tool.type,
                    conversation_id=request.conversation_id,
                    tool_call_latency_ms=_seconds_to_ms(tool_call_elapsed),
                )
                if active_tool.type == ToolType.END_CALL:
                    response_status = ConversationStatus.ENDED
                elif active_tool.type == ToolType.AGENT_TRANSFER:
                    resolved_id = tool_data.get("transferred_to")
                    if resolved_id:
                        # Hand consumers the canonical target: the voice worker
                        # publishes tool_invoked.parameters.targets[0] and the
                        # FE swap matches on it, so the raw config string must
                        # not leak past this point (#212).
                        tool_invoked_override = active_tool.model_copy(
                            update={
                                "parameters": {
                                    **active_tool.parameters,
                                    "targets": [resolved_id],
                                }
                            }
                        )
                    logger.info(
                        "agent_handoff",
                        from_agent=request.agent_config.name,
                        to_agent=tool_data.get("transferred_to"),
                        conversation_id=request.conversation_id,
                    )

        return _DispatchResult(
            early_response=None,
            tool_data=tool_data,
            response_status=response_status,
            llm_text_override=llm_text_override,
            tool_call_elapsed=tool_call_elapsed,
            tool_invoked_override=tool_invoked_override,
        )

    async def _dispatch_tool(
        self,
        tool: ToolDefinition,
        context: dict[str, Any],
        db: AsyncSession | None = None,
        user_id: int | None = None,
    ) -> tuple[dict[str, Any], float]:
        """Execute a tool after the user has confirmed (if required).

        Returns (result_data, elapsed_seconds) for benchmark timing (#68).
        """
        from taskorbit.tools import ToolResult
        from taskorbit.tools.agent_transfer import AgentTransferTool
        from taskorbit.tools.data_extraction import DataExtractionTool
        from taskorbit.tools.end_call import EndCallTool
        from taskorbit.tools.generic_api import GenericApiTool
        from taskorbit.types import ToolType

        _tool_start = time.perf_counter()

        dispatch: dict[ToolType, type] = {
            ToolType.DATA_EXTRACTION: DataExtractionTool,
            ToolType.AGENT_TRANSFER: AgentTransferTool,
            ToolType.END_CALL: EndCallTool,
            ToolType.EXTERNAL_API: GenericApiTool,
        }

        tool_cls = dispatch.get(tool.type)
        if tool_cls is None:
            _tool_elapsed = time.perf_counter() - _tool_start
            logger.warning("unknown_tool_type", tool_type=tool.type, tool_id=tool.id)
            return {}, _tool_elapsed

        if tool.type == ToolType.AGENT_TRANSFER:
            result: ToolResult = await AgentTransferTool(db=db, user_id=user_id).execute(context)
        else:
            result = await tool_cls().execute(context)

        _tool_elapsed = time.perf_counter() - _tool_start
        get_metrics().pipeline_latency_seconds.labels(stage="tool_call").observe(_tool_elapsed)

        if not result.success:
            logger.warning(
                "tool_execution_failed",
                tool_id=tool.id,
                tool_type=tool.type,
                error=result.error,
                tool_call_latency_ms=_seconds_to_ms(_tool_elapsed),
            )
            return {}, _tool_elapsed

        logger.info(
            "tool_executed",
            tool_id=tool.id,
            tool_type=tool.type,
            data=result.data,
            tool_call_latency_ms=_seconds_to_ms(_tool_elapsed),
        )
        return result.data, _tool_elapsed

    _END_CALL_SIGNALS: frozenset[str] = frozenset(
        {
            # Unambiguous farewells
            "goodbye",
            "good bye",
            "bye bye",
            # Explicit end-call phrases
            "end the call",
            "end this call",
            "end call",
            "end the conversation",
            "end this conversation",
            "close the call",
            "terminate the call",
            "hang up",
            "hangup",
            "i want to hang up",
            "i want to end the call",
            "i want to end this call",
            "please end the call",
            "please hang up",
            # Clearly finished
            "that's all i needed",
            "that is all i needed",
            "that's everything i needed",
            "that is everything i needed",
            "no more questions",
            "i have no more questions",
            "i'm done for now",
            "im done for now",
            "we're done here",
            "were done here",
            "i'm ready to end",
            "im ready to end",
            # Wrap-up with explicit call reference
            "wrap up the call",
            "let's end the call",
            "lets end the call",
            # Done for the day / session
            "done for the day",
            "done for today",
            "i'm done for the day",
            "im done for the day",
            "i am done for the day",
            "am done for the day",
            "i think i'm done",
            "i think im done",
            "i think am done",
            "i think i am done",
            "i think that's all",
            "i think thats all",
            "i think that's everything",
            "i think thats everything",
            "i think we're done",
            "i think were done",
            "i guess that's all",
            "i guess thats all",
            "that's it for today",
            "thats it for today",
        }
    )

    _NEGATION_PREFIXES: frozenset[str] = frozenset(
        {
            "don't",
            "dont",
            "do not",
            "won't",
            "wont",
            "will not",
            "can't",
            "cant",
            "cannot",
            "not",
            "never",
            "please don't",
            "please dont",
        }
    )

    def _user_requested_end_call(self, message: str) -> bool:
        """Return True when the user's message contains an explicit end-call signal."""
        lowered = message.lower().strip()
        for signal in self._END_CALL_SIGNALS:
            pos = lowered.find(signal)
            if pos == -1:
                continue
            prefix = lowered[:pos].rstrip()
            if any(prefix.endswith(neg) for neg in self._NEGATION_PREFIXES):
                continue
            return True
        return False

    def _make_assistant_message(self, content: str) -> Message:
        return Message(role=MessageRole.ASSISTANT, content=content)
