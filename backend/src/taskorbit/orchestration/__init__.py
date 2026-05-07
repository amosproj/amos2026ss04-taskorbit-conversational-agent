"""Orchestration engine — the core of TaskOrbit.

ConversationOrchestrator is the single entry point for processing a user
message. It enforces the key architectural invariant: the LLM only ever
sees the context for the *currently active* task, never the full agent
config. This prevents prompt drift and keeps the agent grounded.

Flow per message:
  1. Determine which tool (if any) should be in scope right now.
  2. Build a minimal system prompt from that task context only.
  3. Call the configured LLM provider.
  4. If the LLM wants to invoke a tool, check confirmation requirements
     and either surface a confirmation request or dispatch immediately.
  5. Return a ConversationResponse.
"""

from __future__ import annotations

import asyncio
from typing import Any

from taskorbit.config import Settings, get_settings
from taskorbit.types import (
    AgentConfig,
    ConversationRequest,
    ConversationResponse,
    Message,
    MessageRole,
    ToolDefinition,
)


class ConversationOrchestrator:
    """Routes messages through task selection → LLM → tool dispatch."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def process_message(
        self, request: ConversationRequest
    ) -> ConversationResponse:
        """Main entry point called by the API layer and agent workers.

        Executes the runtime pipeline:
        1. Select active tool/task context.
        2. Build system prompt.
        3. Generate LLM response (with timeout).
        """
        try:
            # 1. Decide which tool context is active
            active_tool = self._select_active_tool(request.messages, request.agent_config)

            # 2. Build the LLM instructions
            system_prompt = self._build_system_prompt(request.agent_config, active_tool)

            # 3. Call LLM with a 10-second timeout
            response_text = await asyncio.wait_for(
                self._call_llm(system_prompt, request.messages),
                timeout=10.0
            )

            return ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message(response_text),
            )

        except asyncio.TimeoutError:
            return ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message(
                    "I'm sorry, I'm having trouble connecting to my brain right now. Please try again."
                ),
            )
        except Exception as e:
            return ConversationResponse(
                conversation_id=request.conversation_id,
                reply=self._make_assistant_message(
                    f"An unexpected error occurred in the runtime: {e!s}"
                ),
            )

    def _build_system_prompt(
        self,
        agent_config: AgentConfig,
        active_tool: ToolDefinition | None,
    ) -> str:
        """Construct a system prompt (LLM context) for the current task."""
        prompt = (
            f"Persona: {agent_config.persona}\n"
            f"Core Instructions: {agent_config.greeting}\n"
        )
        
        if active_tool:
            prompt += f"\nCurrent Task: {active_tool.description}\n"
            prompt += f"Available Parameters: {active_tool.parameters}\n"
            
        return prompt

    def _select_active_tool(
        self,
        messages: list[Message],
        agent_config: AgentConfig,
    ) -> ToolDefinition | None:
        """
        Decide which tool should be in scope for this turn.
        
        MOCK: For now, we just return the first tool if available to demonstrate the pipeline.
        """
        if agent_config.tools:
            return agent_config.tools[0]
        return None

    async def _call_llm(
        self,
        system_prompt: str,
        messages: list[Message],
    ) -> str:
        """
        MOCK: Simulated LLM response until #18 is integrated.
        """
        last_user_msg = next(
            (m.content for m in reversed(messages) if m.role == MessageRole.USER), 
            "Hello"
        )
        
        # Simulate a short processing delay
        await asyncio.sleep(0.5)
        
        return f"[MOCKED LLM] Based on your request '{last_user_msg}', I am helping you with the current task."

    async def _dispatch_tool(
        self,
        tool: ToolDefinition,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        TO-DO: Execute tool calls after confirmation.
        """
        raise NotImplementedError

    def _make_assistant_message(self, content: str) -> Message:
        return Message(role=MessageRole.ASSISTANT, content=content)
