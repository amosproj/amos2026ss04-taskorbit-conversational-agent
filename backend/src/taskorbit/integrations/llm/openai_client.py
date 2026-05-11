"""OpenAI concrete LLM client.

Implements the LLMClient Protocol from base.py by delegating to the official
``openai`` SDK's async client. The factory in factory.py instantiates this
class only when AgentConfig.llm.provider == LLMProvider.OPENAI.

SDK exception mapping: provider-specific exception types are translated into
the taskorbit LLM error hierarchy so callers can catch by failure mode rather
than by SDK internals.
"""

from __future__ import annotations

import openai

from taskorbit.config import Settings
from taskorbit.logging.setup import get_logger
from taskorbit.types import LLMConfig, Message

from .errors import (
    LLMAPIError,
    LLMAuthError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from .messages import to_openai_messages

# HTTP timeout for the SDK — kept slightly under the orchestrator's outer
# asyncio.wait_for(_call_llm, timeout=10.0) so the SDK fails first and we can
# wrap the exception in LLMTimeoutError rather than have the orchestrator's
# generic TimeoutError swallow the provenance.
_REQUEST_TIMEOUT_SECONDS = 8.0

# Built-in SDK retry — the openai SDK retries transient 5xx and network
# errors with exponential backoff. Two retries (three total attempts) is the
# conservative default used elsewhere in the codebase pattern.
_MAX_RETRIES = 2

_log = get_logger(__name__)


class OpenAIClient:
    """LLMClient implementation backed by the openai async SDK."""

    def __init__(self, *, llm_config: LLMConfig, settings: Settings) -> None:
        self._llm_config = llm_config
        self._settings = settings
        self._client = openai.AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            max_retries=_MAX_RETRIES,
        )

    async def generate(
        self,
        system_prompt: str,
        messages: list[Message],
        llm_config: LLMConfig,
    ) -> str:
        """Call OpenAI chat completions and return the assistant text.

        Raises LLMAuthError on 401/403, LLMRateLimitError on 429,
        LLMTimeoutError on request timeout, and LLMAPIError for all other
        provider failures (including an empty response body).
        """
        wire_messages = [
            {"role": "system", "content": system_prompt},
            *to_openai_messages(messages),
        ]

        _log.info(
            "llm_call_started",
            provider="openai",
            model=llm_config.model,
            message_count=len(wire_messages),
        )

        try:
            response = await self._client.chat.completions.create(
                model=llm_config.model,
                messages=wire_messages,
            )
        except openai.AuthenticationError as exc:
            _log.error("llm_call_failed", provider="openai", error_type="auth", error=str(exc))
            raise LLMAuthError(f"OpenAI authentication failed: {exc}") from exc
        except openai.RateLimitError as exc:
            _log.error(
                "llm_call_failed", provider="openai", error_type="rate_limit", error=str(exc)
            )
            raise LLMRateLimitError(f"OpenAI rate-limited: {exc}") from exc
        except openai.APITimeoutError as exc:
            _log.error("llm_call_failed", provider="openai", error_type="timeout", error=str(exc))
            raise LLMTimeoutError(f"OpenAI request timed out: {exc}") from exc
        except openai.APIError as exc:
            _log.error("llm_call_failed", provider="openai", error_type="api", error=str(exc))
            raise LLMAPIError(f"OpenAI API error: {exc}") from exc

        text = response.choices[0].message.content if response.choices else None
        if not text:
            _log.error("llm_call_failed", provider="openai", error_type="empty_response")
            raise LLMAPIError("OpenAI returned an empty response")

        _log.info(
            "llm_call_completed",
            provider="openai",
            model=llm_config.model,
            chars=len(text),
        )
        return text
