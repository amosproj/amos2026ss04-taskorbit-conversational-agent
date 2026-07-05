"""OpenRouter LLM client using the official openrouter Python SDK.

Routes requests to open-source models (Qwen, Gemma, Llama, Mistral, DeepSeek)
via OpenRouter's hosted API. No GPU or local infrastructure required —
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

from openrouter import OpenRouter
from openrouter.errors import (
    EdgeNetworkTimeoutResponseError,
    ForbiddenResponseError,
    OpenRouterError,
    ProviderOverloadedResponseError,
    TooManyRequestsResponseError,
    UnauthorizedResponseError,
)

from taskorbit.config import Settings
from taskorbit.logging.setup import get_logger
from taskorbit.observability.metrics import get_metrics
from taskorbit.types import LLMConfig, Message

from .errors import LLMAPIError, LLMAuthError, LLMRateLimitError, LLMTimeoutError
from .messages import to_openai_messages

_log = get_logger(__name__)

_HTTP_REFERER = "https://taskorbit.app"
_APP_TITLE = "TaskOrbit"


class OpenRouterClient:
    """LLM client backed by the official openrouter Python SDK.

    Supports any model available on OpenRouter, including free-tier open-source
    models (Qwen, Gemma, Llama, Mistral, DeepSeek). Swapping the model requires
    only a config change — no code modification.

    Reasoning content (chain-of-thought from DeepSeek R1, Qwen3, etc.) is
    returned by the SDK in a separate ``message.reasoning`` field and is not
    included in the text this client returns.
    """

    def __init__(self, *, llm_config: LLMConfig, settings: Settings) -> None:
        self._llm_config = llm_config
        self._settings = settings
        self._client = OpenRouter(api_key=settings.openrouter_api_key)

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
            result = await self._client.chat.send_async(
                model=llm_config.model,
                messages=wire_messages,
                http_referer=_HTTP_REFERER,
                x_open_router_title=_APP_TITLE,
            )
        except ForbiddenResponseError as exc:
            _log.error("llm_call_failed", provider="openrouter", error_type="auth", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="auth"
            ).inc()
            raise LLMAuthError(f"OpenRouter authentication failed: {exc}") from exc
        except UnauthorizedResponseError as exc:
            _log.error("llm_call_failed", provider="openrouter", error_type="auth", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="auth"
            ).inc()
            raise LLMAuthError(f"OpenRouter authentication failed: {exc}") from exc
        except EdgeNetworkTimeoutResponseError as exc:
            _log.error(
                "llm_call_failed", provider="openrouter", error_type="timeout", error=str(exc)
            )
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="timeout"
            ).inc()
            raise LLMTimeoutError(f"OpenRouter request timed out: {exc}") from exc
        except (TooManyRequestsResponseError, ProviderOverloadedResponseError) as exc:
            # str(exc) is just "Provider returned error" — exc.body carries the
            # actual reason ("model X is temporarily rate-limited upstream,
            # retry shortly"), essential for diagnosing flaky :free models (#197).
            detail = getattr(exc, "body", None) or str(exc)
            _log.error(
                "llm_call_failed", provider="openrouter", error_type="rate_limit", error=detail
            )
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="rate_limit"
            ).inc()
            raise LLMRateLimitError(f"OpenRouter rate-limited: {detail}") from exc
        except OpenRouterError as exc:
            detail = getattr(exc, "body", None) or str(exc)
            _log.error("llm_call_failed", provider="openrouter", error_type="api", error=detail)
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="api"
            ).inc()
            raise LLMAPIError(f"OpenRouter API error: {detail}") from exc

        raw_content = result.choices[0].message.content if result.choices else None
        if isinstance(raw_content, list):
            text: str | None = (
                "".join(
                    item.get("text", "") if isinstance(item, dict) else str(item)
                    for item in raw_content
                )
                or None
            )
        else:
            text = raw_content or None

        if not text:
            _log.error("llm_call_failed", provider="openrouter", error_type="empty_response")
            get_metrics().llm_requests_total.labels(
                provider="openrouter", model=llm_config.model, status="empty_response"
            ).inc()
            raise LLMAPIError("OpenRouter returned an empty response")

        usage = result.usage
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
        """Yield the complete OpenRouter response as one chunk.

        OpenRouter free-tier models silently return empty SSE streams under
        load — the stream opens and closes with zero content chunks while the
        equivalent non-streaming call succeeds. Delegating to ``generate()``
        avoids that behaviour; all metrics and logging are handled there.
        """
        text = await self.generate(system_prompt, messages, llm_config)
        yield text
