"""Agent transfer tool — hands the conversation off to a different agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from taskorbit.tools import BaseTool, ToolResult
from taskorbit.types import ToolType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _get_known_agent_names() -> frozenset[str]:
    from taskorbit.agents import AgentRegistry

    return AgentRegistry.known_agent_names()


class AgentTransferTool(BaseTool):
    tool_type = ToolType.AGENT_TRANSFER

    def __init__(self, db: AsyncSession | None = None, user_id: int | None = None) -> None:
        self._db = db
        self._user_id = user_id

    async def _is_valid_target(self, target_agent_id: str) -> bool:
        """Return True when target_agent_id is a built-in agent name or a saved custom agent."""
        if target_agent_id in _get_known_agent_names():
            return True
        if self._db is not None:
            from taskorbit.database.crud import get_agent_configuration_by_id

            record = await get_agent_configuration_by_id(
                self._db, target_agent_id, user_id=self._user_id
            )
            return record is not None
        return False

    async def execute(self, parameters: dict[str, Any]) -> ToolResult:
        """Transfer the conversation to another agent, preserving full history.

        Expected parameters:
            target_agent_id (str): built-in agent_name (e.g. "technical_support")
                or the UUID hex ID of a saved custom AgentConfiguration.
            conversation_history (list[dict]): full message list — passed through
                so the new agent has full context.
        """
        target_agent_id = parameters.get("target_agent_id", "").strip()
        if not target_agent_id:
            return ToolResult(success=False, error="target_agent_id is required")

        if not await self._is_valid_target(target_agent_id):
            known = sorted(_get_known_agent_names())
            return ToolResult(
                success=False,
                error=f"Unknown agent '{target_agent_id}'. Valid built-in agents: {known}",
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
        # Synchronous check against built-ins only (used for pre-flight validation).
        # Full validation including custom agents happens async in execute().
        target = parameters.get("target_agent_id", "").strip()
        return bool(target) and target in _get_known_agent_names()
