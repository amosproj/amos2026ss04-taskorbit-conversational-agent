"""Agent transfer tool — hands the conversation off to a different agent."""

from __future__ import annotations

from typing import Any

from taskorbit.tools import BaseTool, ToolResult
from taskorbit.types import ToolType


def _get_known_agent_names() -> frozenset[str]:
    from taskorbit.agents import AgentRegistry

    return frozenset(cls.agent_name for _, cls in AgentRegistry._REGISTRY)


class AgentTransferTool(BaseTool):
    tool_type = ToolType.AGENT_TRANSFER

    async def execute(self, parameters: dict[str, Any]) -> ToolResult:
        """Transfer the conversation to another agent, preserving full history.

        Expected parameters:
            target_agent_id (str): agent_name of the destination agent
                (e.g. "technical_support", "general_inquiry").
            conversation_history (list[dict]): full message list from the
                request — passed through untouched so the new agent has context.
        """
        target_agent_id = parameters.get("target_agent_id", "").strip()
        if not target_agent_id:
            return ToolResult(success=False, error="target_agent_id is required")

        known = _get_known_agent_names()
        if target_agent_id not in known:
            return ToolResult(
                success=False,
                error=f"Unknown agent '{target_agent_id}'. Valid agents: {sorted(known)}",
            )

        conversation_history = parameters.get("conversation_history", [])

        return ToolResult(
            success=True,
            data={
                "transferred_to": target_agent_id,
                "history_preserved": True,
                "message_count": len(conversation_history),
            },
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> bool:
        target = parameters.get("target_agent_id", "").strip()
        return bool(target) and target in _get_known_agent_names()
