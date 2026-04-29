"""Sales agent — qualifies leads, collects contact info, schedules follow-ups."""

from __future__ import annotations

from taskorbit.agents import BaseAgent
from taskorbit.types import ConversationRequest, ConversationResponse, ToolDefinition


class SalesAgent(BaseAgent):
    """Handles lead qualification flows: discovery, data extraction, scheduling."""

    async def handle_message(
        self, request: ConversationRequest
    ) -> ConversationResponse:
        return await self.orchestrator.process_message(request)

    def get_task_definitions(self) -> list[ToolDefinition]:
        raise NotImplementedError
