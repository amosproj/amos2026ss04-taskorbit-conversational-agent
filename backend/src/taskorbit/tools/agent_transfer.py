"""Agent transfer tool — hands the conversation off to a different agent."""

from __future__ import annotations

from typing import Any

from taskorbit.tools import BaseTool, ToolResult
from taskorbit.types import ToolType


class AgentTransferTool(BaseTool):
    tool_type = ToolType.AGENT_TRANSFER

    async def execute(self, parameters: dict[str, Any]) -> ToolResult:
        """
        TO-DO:
        Route to a different agent
        """
        raise NotImplementedError

    def validate_parameters(self, parameters: dict[str, Any]) -> bool:
        """
        TO-DO:
        Schema validation
        """
        raise NotImplementedError
