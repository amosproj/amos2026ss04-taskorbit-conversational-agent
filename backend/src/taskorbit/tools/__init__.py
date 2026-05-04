"""Tool implementations exposed to the LLM.

BaseTool defines the interface every tool must implement. Concrete tools
(data_extraction, agent_transfer, end_call) live in sibling modules and
are registered here so the orchestration layer can look them up by ToolType.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from taskorbit.types import ToolType


@dataclass
class ToolResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class BaseTool(ABC):
    """Abstract base for all tool implementations."""

    tool_type: ClassVar[ToolType]

    @abstractmethod
    async def execute(self, parameters: dict[str, Any]) -> ToolResult:
        """Run the tool. Called only after user confirmation (if required)."""
        ...

    @abstractmethod
    def validate_parameters(self, parameters: dict[str, Any]) -> bool:
        """Return True if parameters satisfy the tool's schema."""
        ...
