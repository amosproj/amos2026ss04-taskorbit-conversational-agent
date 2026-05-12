"""Contract that every concrete LLM client (OpenAIClient, GeminiClient) must satisfy.

Concrete implementations live alongside this file and are instantiated by the
factory in factory.py. Nothing outside this package should depend on a concrete
class — only on LLMClient.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from taskorbit.types import LLMConfig, Message


@runtime_checkable
class LLMClient(Protocol):
    async def generate(
        self,
        system_prompt: str,
        messages: list[Message],
        llm_config: LLMConfig,
    ) -> str:
        """Call the provider and return the raw assistant text.

        Raises LLMTimeoutError if the provider does not respond within the
        configured deadline. Raises LLMAPIError on any upstream failure (auth,
        rate limit, malformed response). Never returns an empty string.
        """
        ...
