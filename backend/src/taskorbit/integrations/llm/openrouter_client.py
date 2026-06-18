"""OpenRouter LLM client.

Routes requests to open-source models (Qwen, Gemma, Llama, Mistral, DeepSeek)
via OpenRouter's OpenAI-compatible API. No GPU or local infrastructure required —
a free API key at https://openrouter.ai/keys is all that is needed.

The free tier includes models marked with the ``:free`` suffix. These are
rate-limited but sufficient for development and light production use. Paid
models are also supported by the same client.

Model names follow OpenRouter's namespaced format: ``<org>/<name>:<variant>``,
e.g. ``meta-llama/llama-3.1-8b-instruct:free``.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator

import openai

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
from .messages import to_openai_messages

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Free-tier models can be slower than paid cloud APIs — use a longer timeout.
_REQUEST_TIMEOUT_SECONDS = 30.0
_MAX_RETRIES = 1

_log = get_logger(__name__)


class OpenRouterClient:
    """LLMClient backed by OpenRouter's OpenAI-compatible API.

    Supports any model available on OpenRouter, including free-tier open-source
    models (Qwen, Gemma, Llama, Mistral, DeepSeek). Swapping the model requires
    only a config change — no code modification.
    """

    def __init__(self, *, llm_config: LLMConfig, settings: Settings) -> None:
        self._llm_config = llm_config
        self._settings = settings
        self._client = openai.AsyncOpenAI(
            base_url=_OPENROUTER_BASE_URL,
            api_key=settings.openrouter_api_key,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            max_retries=_MAX_RETRIES,
            default_headers={
                # OpenRouter uses these for usage tracking and rate-limit tiers.
                "HTTP-Referer": "https://taskorbit.app",
                "X-Title": "TaskOrbit",
            },
        )

    async def generate(
        self,
        system_prompt: str,
        messages: list[Message],
        llm_config: LLMConfig,
    ) -> str:
        """Call OpenRouter chat completions and return the assistant text."""
        wire_messages = [
            {"role": "system", "content": system_prompt},
            *to_openai_messages(messages),
        ]

        _log.info(
            "llm_call_started",
            provider="openrouter",
            model=llm_config.model,
            message_count=len(wire_messages),
        )

        _api_start = time.perf_counter()
        try:
            response = await self._client.chat.completions.create(
                model=llm_config.model,
                messages=wire_messages,
            )
        except openai.AuthenticationError as exc:
            _log.error("llm_call_failed", provider="openrouter", error_type="auth", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="auth"
            ).inc()
            raise LLMAuthError(f"OpenRouter authentication failed: {exc}") from exc
        except openai.RateLimitError as exc:
            _log.error(
                "llm_call_failed", provider="openrouter", error_type="rate_limit", error=str(exc)
            )
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="rate_limit"
            ).inc()
            raise LLMRateLimitError(f"OpenRouter rate-limited: {exc}") from exc
        except openai.APITimeoutError as exc:
            _log.error(
                "llm_call_failed", provider="openrouter", error_type="timeout", error=str(exc)
            )
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="timeout"
            ).inc()
            raise LLMTimeoutError(f"OpenRouter request timed out: {exc}") from exc
        except openai.APIError as exc:
            _log.error("llm_call_failed", provider="openrouter", error_type="api", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="api"
            ).inc()
            raise LLMAPIError(f"OpenRouter API error: {exc}") from exc

        text = response.choices[0].message.content if response.choices else None
        if not text:
            _log.error("llm_call_failed", provider="openrouter", error_type="empty_response")
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="empty_response"
            ).inc()
            raise LLMAPIError("OpenRouter returned an empty response")

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        _api_elapsed = time.perf_counter() - _api_start
        _log.info(
            "llm_call_completed",
            provider="openrouter",
            model=llm_config.model,
            chars=len(text),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            llm_api_latency_ms=round(_api_elapsed * 1000, 1),
        )
        _m = get_metrics()
        _m.llm_requests_total.labels(
            provider="openrouter", model=llm_config.model, status="success"
        ).inc()
        _m.pipeline_latency_seconds.labels(stage="llm_api_openrouter").observe(_api_elapsed)
        _m.llm_response_chars.labels(provider="openrouter", model=llm_config.model).observe(
            len(text)
        )
        _m.tokens_used_total.labels(
            provider="openrouter", model=llm_config.model, token_type="prompt"
        ).inc(prompt_tokens)
        _m.tokens_used_total.labels(
            provider="openrouter", model=llm_config.model, token_type="completion"
        ).inc(completion_tokens)
        return text

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[Message],
        llm_config: LLMConfig,
    ) -> AsyncGenerator[str, None]:
        """Stream the OpenRouter chat completion token by token."""
        wire_messages = [
            {"role": "system", "content": system_prompt},
            *to_openai_messages(messages),
        ]

        _log.info(
            "llm_stream_started",
            provider="openrouter",
            model=llm_config.model,
            message_count=len(wire_messages),
        )

        _api_start = time.perf_counter()
        try:
            stream = await self._client.chat.completions.create(
                model=llm_config.model,
                messages=wire_messages,
                stream=True,
                stream_options={"include_usage": True},
            )
        except openai.AuthenticationError as exc:
            _log.error(
                "llm_stream_failed", provider="openrouter", error_type="auth", error=str(exc)
            )
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="auth"
            ).inc()
            raise LLMAuthError(f"OpenRouter authentication failed: {exc}") from exc
        except openai.RateLimitError as exc:
            _log.error(
                "llm_stream_failed", provider="openrouter", error_type="rate_limit", error=str(exc)
            )
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="rate_limit"
            ).inc()
            raise LLMRateLimitError(f"OpenRouter rate-limited: {exc}") from exc
        except openai.APITimeoutError as exc:
            _log.error(
                "llm_stream_failed", provider="openrouter", error_type="timeout", error=str(exc)
            )
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="timeout"
            ).inc()
            raise LLMTimeoutError(f"OpenRouter request timed out: {exc}") from exc
        except openai.APIError as exc:
            _log.error("llm_stream_failed", provider="openrouter", error_type="api", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="api"
            ).inc()
            raise LLMAPIError(f"OpenRouter API error: {exc}") from exc

        char_count = 0
        usage_chunk = None
        completed = False
        try:
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    char_count += len(delta)
                    yield delta
                if chunk.usage:
                    usage_chunk = chunk.usage
            completed = True
        except openai.APIError as exc:
            _log.error("llm_stream_failed", provider="openrouter", error_type="api", error=str(exc))
            raise LLMAPIError(f"OpenRouter streaming error: {exc}") from exc
        finally:
            await stream.close()
            _api_elapsed = time.perf_counter() - _api_start
            prompt_tokens = usage_chunk.prompt_tokens if usage_chunk else 0
            completion_tokens = usage_chunk.completion_tokens if usage_chunk else 0
            _log.info(
                "llm_stream_completed",
                provider="openrouter",
                model=llm_config.model,
                chars=char_count,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                llm_api_latency_ms=round(_api_elapsed * 1000, 1),
            )
            _m = get_metrics()
            if completed:
                _m.llm_requests_total.labels(
                    provider="openrouter", model=llm_config.model, status="success"
                ).inc()
            _m.pipeline_latency_seconds.labels(stage="llm_api_openrouter").observe(_api_elapsed)
            _m.llm_response_chars.labels(provider="openrouter", model=llm_config.model).observe(
                char_count
            )
            if prompt_tokens:
                _m.tokens_used_total.labels(
                    provider="openrouter", model=llm_config.model, token_type="prompt"
                ).inc(prompt_tokens)
            if completion_tokens:
                _m.tokens_used_total.labels(
                    provider="openrouter", model=llm_config.model, token_type="completion"
                ).inc(completion_tokens)
