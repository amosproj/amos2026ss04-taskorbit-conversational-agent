"""Contract that every concrete LLM client (OpenAIClient, GeminiClient) must satisfy.

Concrete implementations live alongside this file and are instantiated by the
factory in factory.py. Nothing outside this package should depend on a concrete
class — only on LLMClient.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
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

    def generate_stream(
        self,
        system_prompt: str,
        messages: list[Message],
        llm_config: LLMConfig,
    ) -> AsyncGenerator[str, None]:
        """Stream the assistant response token by token.

        Returns an async generator that yields text chunks as they arrive from
        the provider. Raises the same error types as generate() — auth, rate
        limit, timeout, and API errors — on the first iteration if the request
        fails to initiate.
        """
        ...
