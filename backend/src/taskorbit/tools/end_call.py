"""End-call tool — gracefully terminates the LiveKit session."""

from __future__ import annotations

from typing import Any

from taskorbit.tools import BaseTool, ToolResult
from taskorbit.types import ToolType


class EndCallTool(BaseTool):
    tool_type = ToolType.END_CALL

    async def execute(self, parameters: dict[str, Any]) -> ToolResult:
        """Signal that the conversation is complete.

        The LiveKit session teardown is handled by the worker/frontend after
        it receives status="ended" in the ConversationResponse. This tool
        only produces the signal — it does not close the room itself.
        """
        return ToolResult(success=True, data={"ended": True})

    def validate_parameters(self, parameters: dict[str, Any]) -> bool:
        return True
