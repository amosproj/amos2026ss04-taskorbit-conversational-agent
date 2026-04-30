"""End-call tool — gracefully terminates the LiveKit session."""

from __future__ import annotations

from typing import Any

from taskorbit.tools import BaseTool, ToolResult
from taskorbit.types import ToolType


class EndCallTool(BaseTool):
    tool_type = ToolType.END_CALL

    async def execute(self, parameters: dict[str, Any]) -> ToolResult:
        """
        TO-DO:
        Terminate the call/livekit session
        """
        raise NotImplementedError

    def validate_parameters(self, parameters: dict[str, Any]) -> bool:
        """
        TO-DO:
        Schema validation
        """
        raise NotImplementedError
