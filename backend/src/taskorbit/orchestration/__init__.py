"""Orchestration engine — the core of TaskOrbit.

ConversationOrchestrator is the single entry point for processing a user
message. It enforces the key architectural invariant: the LLM only ever
sees the context for the *currently active* task, never the full agent
config. This prevents prompt drift and keeps the agent grounded.

Flow per message:
  1. Detect intent (mocked — always book_service_appointment until issue #18).
  2. Select the agent via AgentRegistry.
  3. Determine which tool (if any) should be in scope right now.
  4. Build a minimal system prompt from that task context only.
  5. Call the LLM provider with a timeout (configurable via settings).
  6. Return a ConversationResponse with intent, agent, and status fields.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from taskorbit.agents import BaseAgent

from taskorbit.config import Settings, get_settings
from taskorbit.integrations.llm.errors import LLMConfigError
from taskorbit.intent import MockIntentDetector
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
        self._intent_detector = MockIntentDetector()

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

            # 1. Detect intent (mocked)
            intent = self._intent_detector.detect(last_user.content)
            logger.info(
                "intent_detected", intent=intent.name, conversation_id=request.conversation_id
            )

            # 2. Select agent — local import avoids circular dependency with agents/__init__.py
            # NOTE: The agent object is currently a no-op placeholder. The orchestrator
            # still drives the pipeline directly from AgentConfig. Wiring the agent
            # logic (e.g. handle_message) will land when real intent routing replaces
            # MockIntentDetector.
            from taskorbit.agents import AgentRegistry

            agent = AgentRegistry.get_agent(request.agent_config, self)
            logger.info(
                "agent_selected",
                agent=type(agent).__name__,
                conversation_id=request.conversation_id,
            )

            # 3. Select active tool
            active_tool = self._select_active_tool(request.messages, agent)

            # 4. Build system prompt
            system_prompt = self._build_system_prompt(request.agent_config, active_tool)

            # 5. Call LLM with a timeout from settings — measure latency
            _llm_start = time.perf_counter()
            llm_text = await asyncio.wait_for(
                self._call_llm(system_prompt, request.messages, request.agent_config.llm),
                timeout=self._settings.llm_timeout_seconds,
            )
            _llm_elapsed = time.perf_counter() - _llm_start
            get_metrics().pipeline_latency_seconds.labels(stage="llm_call").observe(_llm_elapsed)

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
                selected_agent=request.agent_config.name,
                status="success",
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
    ) -> str:
        """Construct a system prompt (LLM context) for the current task."""
        lines = [
            f"You are {agent_config.name}.",
            f"Persona: {agent_config.persona}",
        ]
        if active_tool:
            lines.append(f"Current task: {active_tool.name} - {active_tool.description}")
            if active_tool.parameters:
                lines.append(f"Available parameters: {active_tool.parameters}")
        return "\n".join(lines)

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
        Returns the tool's result payload.
        """
        raise NotImplementedError

    def _make_assistant_message(self, content: str) -> Message:
        return Message(role=MessageRole.ASSISTANT, content=content)
