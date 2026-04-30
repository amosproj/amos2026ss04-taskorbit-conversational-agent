"""Data extraction tool — collects structured data from the conversation."""

from __future__ import annotations

from typing import Any

from taskorbit.tools import BaseTool, ToolResult
from taskorbit.types import ToolType


class DataExtractionTool(BaseTool):
    tool_type = ToolType.DATA_EXTRACTION

    async def execute(self, parameters: dict[str, Any]) -> ToolResult:
        """TO-DO:
        Parse LLM output, validate parameters, return extracted data
        """
        raise NotImplementedError

    def validate_parameters(self, parameters: dict[str, Any]) -> bool:
        """
        TO-DO:
        Schema validation
        """
        raise NotImplementedError
