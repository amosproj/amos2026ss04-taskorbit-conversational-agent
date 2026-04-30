"""Technical support agent — troubleshoots issues and collects diagnostics."""

from __future__ import annotations

from taskorbit.agents import BaseAgent
from taskorbit.types import ConversationRequest, ConversationResponse, ToolDefinition


class TechnicalSupportAgent(BaseAgent):
    """Handles troubleshooting flows: problem diagnosis, data collection, escalation."""

    async def handle_message(
        self, request: ConversationRequest
    ) -> ConversationResponse:
        """TO-DO: Route through orchestrator with task definitions"""

        return await self.orchestrator.process_message(request)

    def get_task_definitions(self) -> list[ToolDefinition]:
        raise NotImplementedError
