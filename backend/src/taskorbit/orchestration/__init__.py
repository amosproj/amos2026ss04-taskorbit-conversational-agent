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

            # 1. Detect intent via LLM-based router
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
            active_tool = self._select_active_tool(request.messages, agent)

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

            # 4. Build system prompt using the routed agent's persona
            agent_config_for_prompt = request.agent_config.model_copy(
                update={"name": f"{request.agent_config.name} ({agent.agent_name})"}
            )
            system_prompt = self._build_system_prompt(
                agent_config_for_prompt, active_tool, slot_result
            )

            # 5. Call LLM with a timeout from settings — measure latency
            _llm_start = time.perf_counter()
            llm_text = await asyncio.wait_for(
                self._call_llm(system_prompt, request.messages, request.agent_config.llm),
                timeout=self._settings.llm_timeout_seconds,
            )
            _llm_elapsed = time.perf_counter() - _llm_start
            get_metrics().pipeline_latency_seconds.labels(stage="llm_call").observe(_llm_elapsed)

            # 5b. Dispatch active tool when slots are complete
            from taskorbit.types import ConversationStatus, ToolType

            tool_data: dict[str, Any] = {}
            response_status = ConversationStatus.SUCCESS

            if active_tool and slot_result.is_complete and intent.required_inputs:
                tool_data = await self._dispatch_tool(active_tool, slot_result.to_dict())
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
                status=response_status,
                extracted_slots=slot_result.to_dict() if slot_result.is_complete else {},
                missing_slots=slot_result.missing,
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
    ) -> str:
        """Construct a system prompt (LLM context) for the current task."""
        from taskorbit.integrations.llm.prompts import with_persona_guardrails

        lines = [
            f"You are {agent_config.name}.",
            f"Persona: {agent_config.persona}",
        ]
        if active_tool:
            lines.append(f"Current task: {active_tool.name} - {active_tool.description}")
            if active_tool.parameters:
                lines.append(f"Available parameters: {active_tool.parameters}")
        if slot_result is not None:
            if slot_result.filled:
                collected = ", ".join(f"{k}={sv.value}" for k, sv in slot_result.filled.items())
                lines.append(f"Collected so far: {collected}")
            if slot_result.missing:
                lines.append(f"Still need from user: {', '.join(slot_result.missing)}")
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
    ) -> ToolDefinition | None:
        """Decide which tool should be in scope for this turn, if any.

        Returns first tool from the agent's own task definitions.
        Real selection based on conversation history lands in a later sprint.
        """
        tools = agent.get_task_definitions()
        return tools[0] if tools else None

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

    def _make_assistant_message(self, content: str) -> Message:
        return Message(role=MessageRole.ASSISTANT, content=content)
