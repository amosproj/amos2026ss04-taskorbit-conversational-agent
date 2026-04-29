"""External-API adapters.

MeisterwerkClient is the single integration point for the Meisterwerk
platform. It handles:
  - Posting data-extraction results back to Meisterwerk after a tool execution
  - Fetching AgentConfig definitions so configs can be managed in the platform
    rather than hardcoded in this repo

All other third-party service calls (Deepgram, ElevenLabs, LLM providers)
are handled inside their respective modules (livekit_agent, orchestration).
"""

from __future__ import annotations

from typing import Any

from taskorbit.types import AgentConfig


class MeisterwerkClient:
    """HTTP client for the Meisterwerk API."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def post_extraction_result(
        self,
        conversation_id: str,
        data: dict[str, Any],
    ) -> None:
        """Send collected data-extraction payload to Meisterwerk.

        Called by DataExtractionTool after the user confirms the action.
        """
        raise NotImplementedError

    async def get_agent_config(self, agent_id: str) -> AgentConfig:
        """Fetch an AgentConfig by ID from the Meisterwerk platform.

        Allows configs to be managed externally rather than bundled in code.
        """
        raise NotImplementedError
