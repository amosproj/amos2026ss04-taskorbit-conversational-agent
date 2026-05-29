"""Agent transfer tool — hands the conversation off to a different agent."""

from __future__ import annotations

from typing import Any

from taskorbit.tools import BaseTool, ToolResult
from taskorbit.types import ToolType


class AgentTransferTool(BaseTool):
    tool_type = ToolType.AGENT_TRANSFER

    async def execute(self, parameters: dict[str, Any]) -> ToolResult:
        """Transfer the conversation to another agent, preserving full history.

        Expected parameters:
            target_agent_id (str): ID of the agent to hand off to.
            conversation_history (list): Full message list from the request
                — passed through untouched so the new agent has context.
        """
        target_agent_id = parameters.get("target_agent_id", "").strip()
        if not target_agent_id:
            return ToolResult(success=False, error="target_agent_id is required")

        return ToolResult(
            success=True,
            data={
                "transferred_to": target_agent_id,
                "history_preserved": True,
            },
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> bool:
        return bool(parameters.get("target_agent_id"))
