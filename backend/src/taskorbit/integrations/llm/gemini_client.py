"""Google Gemini concrete LLM client.

Implements the LLMClient Protocol from base.py by delegating to the official
``google-genai`` SDK's async client. The factory in factory.py instantiates
this class only when AgentConfig.llm.provider == LLMProvider.GOOGLE.

google-genai uses a different shape than OpenAI:
- System instructions live in GenerateContentConfig, not in the contents list.
- Assistant turns use role "model" (not "assistant").
- Exception types are flat: ClientError covers 4xx (with .code attribute for
  401/403/429 discrimination); ServerError covers 5xx; APIError is the base.
"""

from __future__ import annotations

import time

from google import genai
from google.genai import errors as genai_errors
from google.genai.types import GenerateContentConfig, HttpOptions

from taskorbit.config import Settings
from taskorbit.logging.setup import get_logger
from taskorbit.observability.metrics import get_metrics
from taskorbit.types import LLMConfig, Message

from .errors import (
    LLMAPIError,
    LLMAuthError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from .messages import to_gemini_contents

# HTTP timeout in milliseconds. Google enforces a minimum of 10000ms
# (10s) on this option — anything lower is rejected with HTTP 400
# INVALID_ARGUMENT. This sits at the same boundary as the orchestrator's
# outer asyncio.wait_for(_call_llm, timeout=10.0); the outer wait races
# the inner timeout but in practice that's fine — either way the call
# fails fast at the 10s mark.
_REQUEST_TIMEOUT_MS = 10000

_log = get_logger(__name__)


class GeminiClient:
    """LLMClient implementation backed by the google-genai async SDK."""

    def __init__(self, *, llm_config: LLMConfig, settings: Settings) -> None:
        self._llm_config = llm_config
        self._settings = settings
        self._client = genai.Client(
            api_key=settings.google_api_key,
            http_options=HttpOptions(timeout=_REQUEST_TIMEOUT_MS),
        )

    async def generate(
        self,
        system_prompt: str,
        messages: list[Message],
        llm_config: LLMConfig,
    ) -> str:
        """Call Gemini generate_content and return the assistant text.

        Raises LLMAuthError on 401/403, LLMRateLimitError on 429,
        LLMTimeoutError on request timeout, and LLMAPIError for all other
        provider failures (including an empty or blocked response).
        """
        contents = to_gemini_contents(messages)

        _log.info(
            "llm_call_started",
            provider="google",
            model=llm_config.model,
            message_count=len(contents),
        )

        _api_start = time.perf_counter()
        try:
            response = await self._client.aio.models.generate_content(
                model=llm_config.model,
                contents=contents,
                config=GenerateContentConfig(system_instruction=system_prompt),
            )
        except genai_errors.ClientError as exc:
            # ClientError covers 4xx. Discriminate by status code.
            code = getattr(exc, "code", None)
            if code in (401, 403):
                _log.error("llm_call_failed", provider="google", error_type="auth", error=str(exc))
                get_metrics().llm_requests_total.labels(
                    provider="google", model=llm_config.model, status="auth"
                ).inc()
                raise LLMAuthError(f"Google API authentication failed: {exc}") from exc
            if code == 429:
                _log.error(
                    "llm_call_failed", provider="google", error_type="rate_limit", error=str(exc)
                )
                get_metrics().llm_requests_total.labels(
                    provider="google", model=llm_config.model, status="rate_limit"
                ).inc()
                raise LLMRateLimitError(f"Google API rate-limited: {exc}") from exc
            if code == 408:
                _log.error(
                    "llm_call_failed", provider="google", error_type="timeout", error=str(exc)
                )
                get_metrics().llm_requests_total.labels(
                    provider="google", model=llm_config.model, status="timeout"
                ).inc()
                raise LLMTimeoutError(f"Google API request timed out: {exc}") from exc
            _log.error("llm_call_failed", provider="google", error_type="client", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="google", model=llm_config.model, status="client"
            ).inc()
            raise LLMAPIError(f"Google API client error: {exc}") from exc
        except genai_errors.APIError as exc:
            _log.error("llm_call_failed", provider="google", error_type="api", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="google", model=llm_config.model, status="api"
            ).inc()
            raise LLMAPIError(f"Google API error: {exc}") from exc

        text = response.text
        if not text:
            _log.error("llm_call_failed", provider="google", error_type="empty_response")
            get_metrics().llm_requests_total.labels(
                provider="google", model=llm_config.model, status="empty_response"
            ).inc()
            raise LLMAPIError("Google returned an empty response")

        # google-genai places usage metadata on response.usage_metadata
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
        completion_tokens = getattr(usage, "candidates_token_count", 0) or 0

        _api_elapsed = time.perf_counter() - _api_start
        _log.info(
            "llm_call_completed",
            provider="google",
            model=llm_config.model,
            chars=len(text),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            llm_api_latency_ms=round(_api_elapsed * 1000, 1),
        )
        _m = get_metrics()
        _m.llm_requests_total.labels(
            provider="google", model=llm_config.model, status="success"
        ).inc()
        _m.pipeline_latency_seconds.labels(stage="llm_api_google").observe(_api_elapsed)
        _m.llm_response_chars.labels(provider="google", model=llm_config.model).observe(len(text))
        _m.tokens_used_total.labels(
            provider="google", model=llm_config.model, token_type="prompt"
        ).inc(prompt_tokens)
        _m.tokens_used_total.labels(
            provider="google", model=llm_config.model, token_type="completion"
        ).inc(completion_tokens)
        return text
