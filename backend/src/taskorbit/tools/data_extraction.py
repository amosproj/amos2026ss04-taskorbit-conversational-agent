"""Data extraction tool — collects structured data from the conversation."""

from __future__ import annotations

from typing import Any

from taskorbit.tools import BaseTool, ToolResult
from taskorbit.types import ToolType


class DataExtractionTool(BaseTool):
    tool_type = ToolType.DATA_EXTRACTION

    async def execute(self, parameters: dict[str, Any]) -> ToolResult:
        """Return extracted slot values when all required parameters are present."""
        if not self.validate_parameters(parameters):
            missing = [k for k, v in parameters.items() if v is None]
            return ToolResult(
                success=False,
                error=f"Missing required parameters: {missing}",
            )
        return ToolResult(success=True, data=parameters)

    def validate_parameters(self, parameters: dict[str, Any]) -> bool:
        """Return True when every parameter value is non-None."""
        return all(v is not None for v in parameters.values())
