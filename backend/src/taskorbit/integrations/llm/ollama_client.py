"""Ollama LLM client for self-hosted inference on GCE VM with NVIDIA L4 GPU.

Uses the native Ollama /api/chat endpoint (not the OpenAI-compatible /v1 layer)
because the OpenAI-compatible layer does not forward the `think: false` parameter
to the model template — causing Qwen3 and gemma4 to enter extended thinking mode
and return empty `content` fields.

The native API is called directly via httpx. `think: false` is sent at the top
level of the request body as documented at https://ollama.com/blog/thinking-models.

Set OLLAMA_BASE_URL to the GCE VM URL (e.g. http://35.231.129.211:11434).
Set OLLAMA_MODEL to the model tag (e.g. gemma4:26b).
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator

import httpx

from taskorbit.config import Settings
from taskorbit.logging.setup import get_logger
from taskorbit.observability.metrics import get_metrics
from taskorbit.types import LLMConfig, Message

from .errors import LLMAPIError, LLMAuthError, LLMConfigError, LLMTimeoutError
from .messages import to_openai_messages

_REQUEST_TIMEOUT_SECONDS = 300.0

_log = get_logger(__name__)


async def _get_identity_token(audience: str) -> str:
    """Fetch a GCP identity token for *audience*.

    Tries in order:
      1. IDTokenCredentials from GOOGLE_APPLICATION_CREDENTIALS key file (Docker/local SA key)
      2. Metadata server (GCE / Cloud Run — automatic, no config needed)
      3. `gcloud auth print-identity-token` (local dev outside Docker)

    Runs in a thread pool to avoid blocking the event loop.
    Raises LLMAuthError if all strategies fail.
    """
    import asyncio

    def _fetch() -> str:
        import os

        import google.auth.transport.requests

        sa_key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if sa_key_path:
            try:
                import google.oauth2.service_account

                creds = google.oauth2.service_account.IDTokenCredentials.from_service_account_file(
                    sa_key_path,
                    target_audience=audience,
                )
                creds.refresh(google.auth.transport.requests.Request())
                return creds.token
            except Exception as _e:
                _log.debug("ollama_sa_key_auth_failed", path=sa_key_path, error=str(_e))

        try:
            import google.oauth2.id_token

            return google.oauth2.id_token.fetch_id_token(
                google.auth.transport.requests.Request(), audience
            )
        except Exception as _e:
            _log.debug("ollama_metadata_auth_failed", error=str(_e))

        import subprocess

        try:
            result = subprocess.run(
                ["gcloud", "auth", "print-identity-token", f"--audiences={audience}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                token = result.stdout.strip()
                if token:
                    return token
        except FileNotFoundError:
            pass

        raise RuntimeError(
            "Could not obtain a GCP identity token. "
            "Ensure GOOGLE_APPLICATION_CREDENTIALS points to a service account key "
            "with roles/run.invoker on the Ollama service."
        )

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise LLMAuthError(
            f"Failed to fetch GCP identity token for Ollama at {audience!r}. "
            f"Original error: {exc}"
        ) from exc


def _to_ollama_messages(messages: list[Message]) -> list[dict]:
    """Convert internal Message list to Ollama native API format."""
    result = []
    for m in to_openai_messages(messages):
        result.append({"role": m["role"], "content": m["content"]})
    return result


class OllamaClient:
    """LLM client backed by a self-hosted Ollama instance.

    Uses the native Ollama /api/chat endpoint with think=false to suppress
    extended thinking for both Qwen3 and gemma4 model families.
    """

    def __init__(self, *, llm_config: LLMConfig, settings: Settings) -> None:
        self._llm_config = llm_config
        self._settings = settings
        base_url = settings.ollama_base_url.rstrip("/")
        self._base_url = base_url
        self._needs_auth = False
        self._http = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)

    async def _auth_headers(self) -> dict[str, str]:
        if not self._needs_auth:
            return {}
        token = await _get_identity_token(self._base_url)
        return {"Authorization": f"Bearer {token}"}

    async def verify_model_available(self) -> list[str]:
        """Verify the configured model tag exists on the Ollama endpoint.

        Calls the native GET /api/tags endpoint and checks the active model tag
        is among them. Raises LLMConfigError naming the available tags otherwise.
        Returns the available tags on success. Intended for startup validation.
        """
        model = self._llm_config.model
        extra_headers = await self._auth_headers()
        try:
            response = await self._http.get(
                f"{self._base_url}/api/tags",
                headers=extra_headers,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as exc:
            raise LLMAPIError(f"Timed out listing models at {self._base_url}: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise LLMAuthError(
                    f"Ollama authentication failed while verifying models at {self._base_url}: {exc}"
                ) from exc
            raise LLMAPIError(
                f"Failed to list models at Ollama endpoint {self._base_url}: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMAPIError(
                f"Failed to list models at Ollama endpoint {self._base_url}: {exc}"
            ) from exc
        except ValueError as exc:
            # response.json() raises json.JSONDecodeError (a ValueError) when
            # Ollama returns a malformed body, e.g. a reverse-proxy HTML error
            # page fronting the endpoint or a truncated body on a socket close
            # that still parses as HTTP 200. httpx catches above do not cover
            # this. Parity extension of Vineesh's #197 review to Ollama.
            raise LLMAPIError(f"Ollama returned malformed JSON at {self._base_url}: {exc}") from exc

        available = [m.get("name", "") for m in data.get("models", [])]
        if model not in available:
            raise LLMConfigError(
                f"Ollama model {model!r} is not available at {self._base_url}. "
                f"Available models: {available or '[none]'}. "
                f"Pull it with `ollama pull {model}`."
            )
        return available

    async def generate(
        self,
        system_prompt: str,
        messages: list[Message],
        llm_config: LLMConfig,
    ) -> str:
        ollama_messages = [
            {"role": "system", "content": system_prompt},
            *_to_ollama_messages(messages),
        ]

        _log.info(
            "llm_call_started",
            provider="ollama",
            model=llm_config.model,
            message_count=len(ollama_messages),
        )

        extra_headers = await self._auth_headers()
        payload = {
            "model": llm_config.model,
            "think": False,
            "stream": False,
            "messages": ollama_messages,
        }

        _api_start = time.perf_counter()
        try:
            response = await self._http.post(
                f"{self._base_url}/api/chat",
                json=payload,
                headers=extra_headers,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as exc:
            _log.error("llm_call_failed", provider="ollama", error_type="timeout", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="ollama", model=llm_config.model, status="timeout"
            ).inc()
            raise LLMTimeoutError(f"Ollama request timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                _log.error("llm_call_failed", provider="ollama", error_type="auth", error=str(exc))
                get_metrics().llm_requests_total.labels(
                    provider="ollama", model=llm_config.model, status="auth"
                ).inc()
                raise LLMAuthError(f"Ollama authentication failed: {exc}") from exc
            _log.error("llm_call_failed", provider="ollama", error_type="api", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="ollama", model=llm_config.model, status="api"
            ).inc()
            raise LLMAPIError(f"Ollama API error: {exc}") from exc
        except httpx.HTTPError as exc:
            _log.error("llm_call_failed", provider="ollama", error_type="api", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="ollama", model=llm_config.model, status="api"
            ).inc()
            raise LLMAPIError(f"Ollama API error: {exc}") from exc
        except ValueError as exc:
            # response.json() raises json.JSONDecodeError (a ValueError) when
            # Ollama returns a malformed body, e.g. a reverse-proxy HTML error
            # page or a truncated body. Parity extension of Vineesh's #197
            # review to Ollama.
            _log.error("llm_call_failed", provider="ollama", error_type="decode", error=str(exc))
            get_metrics().llm_requests_total.labels(
                provider="ollama", model=llm_config.model, status="decode_error"
            ).inc()
            raise LLMAPIError(f"Ollama returned malformed JSON: {exc}") from exc

        text = data.get("message", {}).get("content", "")
        if not text:
            _log.error("llm_call_failed", provider="ollama", error_type="empty_response")
            get_metrics().llm_requests_total.labels(
                provider="ollama", model=llm_config.model, status="empty_response"
            ).inc()
            raise LLMAPIError("Ollama returned an empty response")

        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)

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
        """Stream tokens from Ollama using the native /api/chat streaming endpoint."""
        ollama_messages = [
            {"role": "system", "content": system_prompt},
            *_to_ollama_messages(messages),
        ]

        _log.info(
            "llm_stream_started",
            provider="ollama",
            model=llm_config.model,
            message_count=len(ollama_messages),
        )

        extra_headers = await self._auth_headers()
        payload = {
            "model": llm_config.model,
            "think": False,
            "stream": True,
            "messages": ollama_messages,
        }

        _api_start = time.perf_counter()
        char_count = 0
        completed = False
        prompt_tokens = 0
        completion_tokens = 0
        try:
            async with self._http.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json=payload,
                headers=extra_headers,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = __import__("json").loads(line)
                    except ValueError:
                        continue
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        char_count += len(delta)
                        yield delta
                    if chunk.get("done"):
                        completed = True
                        # Ollama reports token counts in the final done=true chunk
                        prompt_tokens = chunk.get("prompt_eval_count", 0)
                        completion_tokens = chunk.get("eval_count", 0)
                        break
        except httpx.TimeoutException as exc:
            _log.error("llm_stream_failed", provider="ollama", error_type="timeout", error=str(exc))
            raise LLMTimeoutError(f"Ollama stream timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                _log.error(
                    "llm_stream_failed", provider="ollama", error_type="auth", error=str(exc)
                )
                raise LLMAuthError(f"Ollama authentication failed: {exc}") from exc
            _log.error("llm_stream_failed", provider="ollama", error_type="api", error=str(exc))
            raise LLMAPIError(f"Ollama streaming error: {exc}") from exc
        except httpx.HTTPError as exc:
            _log.error("llm_stream_failed", provider="ollama", error_type="api", error=str(exc))
            raise LLMAPIError(f"Ollama streaming error: {exc}") from exc
        finally:
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
                _m.tokens_used_total.labels(
                    provider="ollama", model=llm_config.model, token_type="prompt"
                ).inc(prompt_tokens)
                _m.tokens_used_total.labels(
                    provider="ollama", model=llm_config.model, token_type="completion"
                ).inc(completion_tokens)
            _m.pipeline_latency_seconds.labels(stage="llm_api_ollama").observe(_api_elapsed)
            _m.llm_response_chars.labels(provider="ollama", model=llm_config.model).observe(
                char_count
            )
