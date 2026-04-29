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
        """
        raise NotImplementedError

    def _build_system_prompt(
        self,
        agent_config: AgentConfig,
        active_tool: ToolDefinition | None,
    ) -> str:
        """Construct a focused system prompt for the current task.

        Only includes context relevant to `active_tool` (or the agent
        persona if no tool is active). This is what keeps the LLM bounded.
        """
        raise NotImplementedError

    def _select_active_tool(
        self,
        messages: list[Message],
        agent_config: AgentConfig,
    ) -> ToolDefinition | None:
        """Decide which tool should be in scope for this turn, if any.

        Returns None when the conversation is in a free-form phase (e.g.
        greeting, small-talk before a task begins).
        """
        raise NotImplementedError

    async def _call_llm(
        self,
        system_prompt: str,
        messages: list[Message],
    ) -> str:
        """Call the LLM provider configured in settings.

        Returns the raw assistant text. Tool-call parsing happens in the
        caller so this method stays provider-agnostic.
        """
        raise NotImplementedError

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
