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

from typing import Any

from taskorbit.config import Settings, get_settings
from taskorbit.types import (
    AgentConfig,
    ConversationRequest,
    ConversationResponse,
    LLMConfig,
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

        Returns a ConversationResponse containing the assistant reply and,
        when applicable, a pending tool invocation requiring confirmation.

        Current implementation: dummy echo — confirms the pipeline is wired
        end-to-end. Replace with _select_active_tool → _build_system_prompt
        → _call_llm → _dispatch_tool when the LLM integration lands.
        """
        last_user = next(
            (m for m in reversed(request.messages) if m.role == MessageRole.USER),
            None,
        )
        #return response on the frontend


        if last_user:
            """
            TO-DO: replace with actual LLM response once implemented.
            For now we just echo the user's last message to confirm the pipeline is
            working end-to-end."""

            text = f'[Backend echo] I received: "{last_user.content}"'

        else:
            """TO-DO: handle edge case where no user message is found.
            This shouldn't happen in normal flow since the frontend should
            always send the user's message as part of the ConversationRequest,
            but we should still handle it just in case."""

            text = f"Hello! I'm {request.agent_config.name}. How can I help you?"

        return ConversationResponse(
            conversation_id=request.conversation_id,
            reply=self._make_assistant_message(text),
        )

    def _build_system_prompt(
        self,
        agent_config: AgentConfig,
        active_tool: ToolDefinition | None,
    ) -> str:
        """
        TO-DO:
        Construct a system prompt (LLM context)for the current task.

        Only includes context relevant to `active_tool` (or the agent
        persona if no tool is active).
        """
        raise NotImplementedError

    def _select_active_tool(
        self,
        messages: list[Message],
        agent_config: AgentConfig,
    ) -> ToolDefinition | None:

        """
        TO-DO:
        Decide which tool should be in scope for this turn, if any.

        Determine which tool (if any) should be active based on message history.

        Returns None when the conversation is in a free-form phase (e.g.
        greeting, small-talk before a task begins).
        """
        raise NotImplementedError

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
        """
        TO-DO:
        Execute a tool after the user has confirmed (if required).

        Delegates to the concrete BaseTool implementation in taskorbit.tools.
        Returns the tool's result payload.
        """
        raise NotImplementedError

    def _make_assistant_message(self, content: str) -> Message:
        return Message(role=MessageRole.ASSISTANT, content=content)
