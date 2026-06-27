"""Ollama LLM client for self-hosted inference on Cloud Run with NVIDIA L4 GPU.

Ollama exposes an OpenAI-compatible /v1 API so we reuse the openai SDK.
For HTTPS endpoints (Cloud Run), requests carry a GCP identity token obtained
via the metadata server — no API key is stored in code or Secret Manager.
For plain HTTP endpoints (local Ollama install), auth is skipped entirely.

Set OLLAMA_BASE_URL to the Cloud Run service URL and OLLAMA_MODEL to the
model tag. Both are injected as Cloud Run env vars from Secret Manager;
see terraform/modules/cloud_run/main.tf for the wiring.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator

import openai

from taskorbit.config import Settings
from taskorbit.logging.setup import get_logger
from taskorbit.observability.metrics import get_metrics
from taskorbit.types import LLMConfig, Message

from .errors import LLMAPIError, LLMAuthError, LLMTimeoutError
from .messages import to_openai_messages

_REQUEST_TIMEOUT_SECONDS = 60.0  # GPU cold start + inference can take ~30 s on first token
_MAX_RETRIES = 1  # one retry — GPU instance may be warming up

_log = get_logger(__name__)


def _is_https(url: str) -> bool:
    return url.startswith("https://")


async def _get_identity_token(audience: str) -> str:
    """Fetch a GCP identity token for *audience* via the metadata server.

    Runs in a thread pool to avoid blocking the event loop during the HTTP call.
    Raises LLMAuthError if the metadata server is unreachable (not on GCP).
    """
    import asyncio

    def _fetch() -> str:
        import google.auth.transport.requests
        import google.oauth2.id_token

        request = google.auth.transport.requests.Request()
        return google.oauth2.id_token.fetch_id_token(request, audience)

    try:
        return await asyncio.get_event_loop().run_in_executor(None, _fetch)
    except Exception as exc:
        raise LLMAuthError(
            f"Failed to fetch GCP identity token for Ollama at {audience!r}. "
            "Is this running on GCP (Cloud Run / GCE)? "
            f"Original error: {exc}"
        ) from exc


class OllamaClient:
    """LLMClient backed by a self-hosted Ollama instance.

    Uses the Ollama OpenAI-compatible /v1 endpoint so the same openai SDK
    that powers OpenAIClient works here with only a base_url change.

    HTTPS endpoints (Cloud Run) are authenticated with a per-request GCP
    identity token. HTTP endpoints (local) are unauthenticated.
    """

    def __init__(self, *, llm_config: LLMConfig, settings: Settings) -> None:
        self._llm_config = llm_config
        self._settings = settings
        base_url = settings.ollama_base_url.rstrip("/")
        self._base_url = base_url
        self._needs_auth = _is_https(base_url)
        # api_key="ollama" satisfies the SDK's non-empty check; Ollama ignores it.
        self._client = openai.AsyncOpenAI(
            base_url=f"{base_url}/v1",
            api_key="ollama",
            timeout=_REQUEST_TIMEOUT_SECONDS,
            max_retries=_MAX_RETRIES,
        )

    async def _auth_headers(self) -> dict[str, str]:
        if not self._needs_auth:
            return {}
        token = await _get_identity_token(self._base_url)
        return {"Authorization": f"Bearer {token}"}

    async def generate(
        self,
        system_prompt: str,
        messages: list[Message],
        llm_config: LLMConfig,
    ) -> str:
        wire_messages = [
            {"role": "system", "content": system_prompt},
            *to_openai_messages(messages),
        ]

        _log.info(
            "llm_call_started",
            provider="ollama",
            model=llm_config.model,
            message_count=len(wire_messages),
        )

        extra_headers = await self._auth_headers()

        _api_start = time.perf_counter()
        try:
            response = await self._client.chat.completions.create(
                model=llm_config.model,
                messages=wire_messages,
                extra_headers=extra_headers,
            )
        except openai.AuthenticationError as exc:
            _log.error("llm_call_failed", provider="ollama", error_type="auth", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="ollama", model=llm_config.model, status="auth"
            ).inc()
            raise LLMAuthError(f"Ollama authentication failed: {exc}") from exc
        except openai.APITimeoutError as exc:
            _log.error("llm_call_failed", provider="ollama", error_type="timeout", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="ollama", model=llm_config.model, status="timeout"
            ).inc()
            raise LLMTimeoutError(f"Ollama request timed out: {exc}") from exc
        except openai.APIError as exc:
            _log.error("llm_call_failed", provider="ollama", error_type="api", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="ollama", model=llm_config.model, status="api"
            ).inc()
            raise LLMAPIError(f"Ollama API error: {exc}") from exc

        text = response.choices[0].message.content if response.choices else None
        if not text:
            _log.error("llm_call_failed", provider="ollama", error_type="empty_response")
            get_metrics().llm_requests_total.labels(
                provider="ollama", model=llm_config.model, status="empty_response"
            ).inc()
            raise LLMAPIError("Ollama returned an empty response")

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        _api_elapsed = time.perf_counter() - _api_start
        _log.info(
            "llm_call_completed",
            provider="ollama",
            model=llm_config.model,
            chars=len(text),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            llm_api_latency_ms=round(_api_elapsed * 1000, 1),
        )
        _m = get_metrics()
        _m.llm_requests_total.labels(
            provider="ollama", model=llm_config.model, status="success"
        ).inc()
        _m.pipeline_latency_seconds.labels(stage="llm_api_ollama").observe(_api_elapsed)
        _m.llm_response_chars.labels(provider="ollama", model=llm_config.model).observe(len(text))
        _m.tokens_used_total.labels(
            provider="ollama", model=llm_config.model, token_type="prompt"
        ).inc(prompt_tokens)
        _m.tokens_used_total.labels(
            provider="ollama", model=llm_config.model, token_type="completion"
        ).inc(completion_tokens)
        return text

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[Message],
        llm_config: LLMConfig,
    ) -> AsyncGenerator[str, None]:
        """Stream tokens from Ollama.

        Ollama streaming is reliable (unlike some hosted free-tier providers),
        so we use it directly rather than delegating to generate().
        """
        wire_messages = [
            {"role": "system", "content": system_prompt},
            *to_openai_messages(messages),
        ]

        _log.info(
            "llm_stream_started",
            provider="ollama",
            model=llm_config.model,
            message_count=len(wire_messages),
        )

        extra_headers = await self._auth_headers()

        _api_start = time.perf_counter()
        try:
            stream = await self._client.chat.completions.create(
                model=llm_config.model,
                messages=wire_messages,
                stream=True,
                extra_headers=extra_headers,
            )
        except openai.AuthenticationError as exc:
            _log.error("llm_stream_failed", provider="ollama", error_type="auth", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="ollama", model=llm_config.model, status="auth"
            ).inc()
            raise LLMAuthError(f"Ollama authentication failed: {exc}") from exc
        except openai.APITimeoutError as exc:
            _log.error("llm_stream_failed", provider="ollama", error_type="timeout", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="ollama", model=llm_config.model, status="timeout"
            ).inc()
            raise LLMTimeoutError(f"Ollama request timed out: {exc}") from exc
        except openai.APIError as exc:
            _log.error("llm_stream_failed", provider="ollama", error_type="api", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="ollama", model=llm_config.model, status="api"
            ).inc()
            raise LLMAPIError(f"Ollama API error: {exc}") from exc

        char_count = 0
        completed = False
        try:
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    char_count += len(delta)
                    yield delta
            completed = True
        except openai.APIError as exc:
            _log.error("llm_stream_failed", provider="ollama", error_type="api", error=str(exc))
            raise LLMAPIError(f"Ollama streaming error: {exc}") from exc
        finally:
            await stream.close()
            _api_elapsed = time.perf_counter() - _api_start
            _log.info(
                "llm_stream_completed",
                provider="ollama",
                model=llm_config.model,
                chars=char_count,
                llm_api_latency_ms=round(_api_elapsed * 1000, 1),
            )
            _m = get_metrics()
            if completed:
                _m.llm_requests_total.labels(
                    provider="ollama", model=llm_config.model, status="success"
                ).inc()
            _m.pipeline_latency_seconds.labels(stage="llm_api_ollama").observe(_api_elapsed)
            _m.llm_response_chars.labels(provider="ollama", model=llm_config.model).observe(
                char_count
            )
