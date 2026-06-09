"""Orchestration engine — the core of TaskOrbit.

ConversationOrchestrator is the single entry point for processing a user
message. It enforces the key architectural invariant: the LLM only ever
sees the context for the *currently active* task, never the full agent
config. This prevents prompt drift and keeps the agent grounded.

Flow per message:
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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from taskorbit.agents import BaseAgent

from taskorbit.config import Settings, get_settings
from taskorbit.integrations.llm.errors import LLMConfigError
from taskorbit.intent import IntentRouter
from taskorbit.logging.setup import get_logger
from taskorbit.observability.metrics import get_metrics
from taskorbit.types import (
    AgentConfig,
    ContextLimitConfig,
    ConversationRequest,
    ConversationResponse,
    LLMConfig,
    Message,
    MessageRole,
    ToolDefinition,
)

logger = get_logger(__name__)


class ConversationOrchestrator:
    """Routes messages through intent detection → agent → LLM → response."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._intent_router = IntentRouter()

    async def process_message(self, request: ConversationRequest) -> ConversationResponse:
        """Main entry point called by the API layer and agent workers."""
        _pipeline_start = time.perf_counter()
        try:
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
                message_snippet=last_user.content[:60],
            )
            if end_call_tool and self._user_requested_end_call(last_user.content):
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
                await self._dispatch_tool(end_call_tool, {})
                logger.info(
                    "end_call_user_initiated",
                    conversation_id=request.conversation_id,
                )
                return ConversationResponse(
                    conversation_id=request.conversation_id,
                    reply=self._make_assistant_message(farewell),
                    status=ConversationStatus.ENDED,
                    selected_intent="",
                    selected_agent="",
                    tool_invoked=end_call_tool,
                )

            # 1. Detect intent — reuse locked intent when set, but still run the
            # classifier to allow genuine topic changes to break the lock.
            from dataclasses import replace as _replace

            from taskorbit.intent import _KNOWN_INTENTS

            if request.current_intent_name and request.current_intent_name in _KNOWN_INTENTS:
                fresh = await self._intent_router.detect(
                    last_user.content,
                    request.messages,
                    self._call_llm,
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
                    intent = _replace(_KNOWN_INTENTS[request.current_intent_name], confidence=1.0)
                    logger.info(
                        "intent_locked",
                        intent=intent.name,
                        conversation_id=request.conversation_id,
                    )
            else:
                intent = await self._intent_router.detect(
                    last_user.content,
                    request.messages,
                    self._call_llm,
                    request.agent_config.llm,
                )
                logger.info(
                    "intent_detected",
                    intent=intent.name,
                    confidence=intent.confidence,
                    conversation_id=request.conversation_id,
                )

            # Short-circuit: ask for clarification instead of guessing
            if intent.requires_clarification:
                from taskorbit.intent import _CLARIFICATION_REPLY
                from taskorbit.types import ConversationStatus

                return ConversationResponse(
                    conversation_id=request.conversation_id,
                    reply=self._make_assistant_message(_CLARIFICATION_REPLY),
                    status=ConversationStatus.CLARIFICATION,
                    selected_intent=intent.name,
                    selected_agent="",
                    intent_confidence=intent.confidence,
                )

            # 2. Select agent based on detected intent, not config.id
            from taskorbit.agents import AgentRegistry

            agent = AgentRegistry.create_by_name(intent.agent_name, request.agent_config, self)
            logger.info(
                "agent_selected",
                agent=agent.agent_name,
                conversation_id=request.conversation_id,
            )

            # 3. Select active tool
            active_tool = self._select_active_tool(
                request.messages, agent, active_tool_id=request.active_tool_id
            )

            # 3b. Extract slots from conversation history
            slot_result = await self._extract_slots(
                request.messages, intent.required_inputs, request.agent_config.llm
            )
            logger.info(
                "slots_extracted",
                filled=list(slot_result.filled.keys()),
                missing=slot_result.missing,
                conversation_id=request.conversation_id,
            )

            # 4. Build system prompt using the routed agent's role
            system_prompt = self._build_system_prompt(
                request.agent_config, active_tool, slot_result, routed_agent=agent
            )

            # 4b. Truncate conversation history if context limit is configured
            truncated_messages = self._truncate_messages(
                request.messages, request.agent_config.context_limit
            )

            # 5. Call LLM with a timeout from settings — measure latency
            _llm_start = time.perf_counter()
            llm_text = await asyncio.wait_for(
                self._call_llm(system_prompt, truncated_messages, request.agent_config.llm),
                timeout=self._settings.llm_timeout_seconds,
            )
            _llm_elapsed = time.perf_counter() - _llm_start
            get_metrics().pipeline_latency_seconds.labels(stage="llm_call").observe(_llm_elapsed)

            # 5b. Dispatch active tool when slots are complete
            from taskorbit.types import (
                ConfirmationResponsePayload,
                ConversationStatus,
                ToolType,
            )

            tool_data: dict[str, Any] = {}
            response_status = ConversationStatus.SUCCESS

            no_slots_tool_ready = active_tool is not None and active_tool.type in (
                ToolType.END_CALL,
                ToolType.AGENT_TRANSFER,
            )
            slots_ready = (
                active_tool is not None and slot_result.is_complete and bool(intent.required_inputs)
            )

            if no_slots_tool_ready or slots_ready:
                # AC #49: mid-call confirmation logic (Dhruvin's contract).
                is_decision_for_this_tool = request.confirmation_id == active_tool.id
                has_decision = is_decision_for_this_tool and request.decision is not None

                if active_tool.confirmation.required and not has_decision:
                    logger.info(
                        "confirmation_required",
                        tool_id=active_tool.id,
                        conversation_id=request.conversation_id,
                    )
                    return ConversationResponse(
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
                    )

                if has_decision and request.decision == "reject":
                    logger.info(
                        "tool_execution_rejected",
                        tool_id=active_tool.id,
                        conversation_id=request.conversation_id,
                    )
                    response_status = ConversationStatus.REJECTED
                    # Mark as "aborted" so we advance to the next tool/step
                    tool_data = {"aborted": True}
                    llm_text = "Understood. I've cancelled that action. How else can I help you?"
                else:
                    # Proceed either because it's confirmed or not required
                    dispatch_context: dict[str, Any] = dict(slot_result.to_dict())
                    if active_tool.type == ToolType.AGENT_TRANSFER:
                        targets = active_tool.parameters.get("targets") or []
                        if targets:
                            raw = str(targets[0])
                            normalized = raw.removesuffix("-agent").replace("-", "_")
                            dispatch_context["target_agent_id"] = normalized
                        dispatch_context["conversation_history"] = [
                            {"role": m.role.value, "content": m.content} for m in request.messages
                        ]
                    tool_data = await self._dispatch_tool(active_tool, dispatch_context)
                    logger.info(
                        "tool_dispatch_complete",
                        tool_type=active_tool.type,
                        conversation_id=request.conversation_id,
                    )
                    if active_tool.type == ToolType.END_CALL:
                        response_status = ConversationStatus.ENDED
                    elif active_tool.type == ToolType.AGENT_TRANSFER:
                        logger.info(
                            "agent_handoff",
                            from_agent=request.agent_config.name,
                            to_agent=tool_data.get("transferred_to"),
                            conversation_id=request.conversation_id,
                        )

            # Advance to the next tool when the current one was dispatched,
            # so sequential workflows (e.g. data_extraction → end_call) complete.
            if tool_data and active_tool:
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
                llm_latency_ms=round(_llm_elapsed * 1000, 1),
                total_latency_ms=round(_total_elapsed * 1000, 1),
            )

            return ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message(llm_text),
                selected_intent=intent.name,
                selected_agent=agent.agent_name,
                intent_confidence=intent.confidence,
                status=response_status,
                extracted_slots=slot_result.to_dict() if slot_result.is_complete else {},
                missing_slots=slot_result.missing,
                tool_invoked=active_tool if tool_data else None,
                locked_intent_name=intent.name,
                next_active_tool_id=next_active_tool_id,
            )

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
        except TimeoutError:
            get_metrics().conversation_errors_total.labels(error_type="llm_timeout").inc()
            logger.warning("llm_timeout", conversation_id=request.conversation_id)
            return ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message(
                    "I'm sorry, I'm having trouble connecting to my brain right now. Please try again."
                ),
                status="error",
                error=f"LLM call timed out after {self._settings.llm_timeout_seconds} seconds.",
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
        """Cap conversation history at ``context_limit.value`` non-system messages.

        FIFO: when the cap is exceeded, the oldest non-system messages are
        dropped first. System messages are always preserved regardless of
        the cap (the foundational system prompt must never be truncated).

        Returns the full history unchanged when no ``context_limit`` is
        configured or when the history is already within the cap.
        """
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
        """Run slot extraction over the conversation history.

        Returns SlotExtractionResult. Falls back to all-missing on any error
        so the main conversation turn is never blocked by extraction failures.
        """
        from taskorbit.slots import SlotExtractionResult, SlotExtractor

        if not required_inputs:
            return SlotExtractionResult()
        try:
            extractor = SlotExtractor(llm_fn=self._call_llm, llm_config=llm_config)
            return await extractor.extract(messages, required_inputs)
        except Exception as exc:
            logger.warning(
                "slot_extraction_error",
                error=str(exc),
            )
            missing = [f["name"] for f in required_inputs if f.get("required", True)]
            return SlotExtractionResult(missing=missing)

    def _select_active_tool(
        self,
        messages: list[Message],
        agent: BaseAgent,
        active_tool_id: str | None = None,
    ) -> ToolDefinition | None:
        """Decide which tool should be in scope for this turn, if any.

        Uses active_tool_id to resume a previously selected tool across turns.
        Falls back to the first tool in the agent's list when no id is provided.
        """
        tools = agent.get_task_definitions()
        if not tools:
            return None
        if active_tool_id:
            match = next((t for t in tools if t.id == active_tool_id), None)
            if match:
                return match
        return tools[0]

    async def _call_llm(
        self,
        system_prompt: str,
        messages: list[Message],
        llm_config: LLMConfig,
    ) -> str:
        """Call the LLM provider specified by ``llm_config`` and return its text.

        Routes to the right concrete client via the factory in
        ``integrations/llm/factory.py``. The same-language instruction is
        appended to the system prompt before delegation so every provider
        receives the multilingual directive consistently. Tool-call parsing
        happens in the caller so this method stays provider-agnostic.
        """
        from taskorbit.integrations.llm.factory import get_llm_client
        from taskorbit.integrations.llm.prompts import with_same_language_instruction

        augmented_prompt = with_same_language_instruction(system_prompt)
        client = get_llm_client(llm_config, settings=self._settings)
        return await client.generate(augmented_prompt, messages, llm_config)

    async def _dispatch_tool(
        self,
        tool: ToolDefinition,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a tool after the user has confirmed (if required).

        Delegates to the concrete BaseTool implementation in taskorbit.tools.
        Returns the tool's result payload, or empty dict on failure.
        """
        from taskorbit.tools import ToolResult
        from taskorbit.tools.agent_transfer import AgentTransferTool
        from taskorbit.tools.data_extraction import DataExtractionTool
        from taskorbit.tools.end_call import EndCallTool
        from taskorbit.types import ToolType

        dispatch: dict[ToolType, type] = {
            ToolType.DATA_EXTRACTION: DataExtractionTool,
            ToolType.AGENT_TRANSFER: AgentTransferTool,
            ToolType.END_CALL: EndCallTool,
        }

        tool_cls = dispatch.get(tool.type)
        if tool_cls is None:
            logger.warning("unknown_tool_type", tool_type=tool.type, tool_id=tool.id)
            return {}

        result: ToolResult = await tool_cls().execute(context)

        if not result.success:
            logger.warning(
                "tool_execution_failed",
                tool_id=tool.id,
                tool_type=tool.type,
                error=result.error,
            )
            return {}

        logger.info(
            "tool_executed",
            tool_id=tool.id,
            tool_type=tool.type,
            data=result.data,
        )
        return result.data

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

    def _user_requested_end_call(self, message: str) -> bool:
        """Return True when the user's message contains an explicit end-call signal."""
        lowered = message.lower()
        return any(signal in lowered for signal in self._END_CALL_SIGNALS)

    def _make_assistant_message(self, content: str) -> Message:
        return Message(role=MessageRole.ASSISTANT, content=content)
