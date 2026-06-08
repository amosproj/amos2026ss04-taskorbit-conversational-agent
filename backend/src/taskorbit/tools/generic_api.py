"""Generic external-API adapter tool (#66).

`GenericApiTool` is a single BaseTool subclass whose behaviour is fully
driven by configuration carried on `ToolDefinition.parameters`. This
lets system admins add new external tools (CRM lookups, weather APIs,
Slack/Zapier webhooks, etc.) by writing a config block instead of new
Python code.

The config shape, env-var substitution, HTTP execution, response
extraction, and error normalisation are implemented in later stages
of #66. This stub keeps the dispatch table consistent so the rest of
the pipeline can already route EXTERNAL_API tools while the body is
being built up incrementally.
"""

from __future__ import annotations

from typing import Any

from taskorbit.tools import BaseTool, ToolResult
from taskorbit.types import ToolType


class GenericApiTool(BaseTool):
    tool_type = ToolType.EXTERNAL_API

    async def execute(self, parameters: dict[str, Any]) -> ToolResult:
        """Stub: real HTTP + extraction + error normalisation lands in #66 stages 2-5."""
        return ToolResult(
            success=False,
            error="GenericApiTool execute() is not implemented yet (#66 stage 1 stub).",
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> bool:
        """Stub: real validation lands alongside the config schema."""
        return False
