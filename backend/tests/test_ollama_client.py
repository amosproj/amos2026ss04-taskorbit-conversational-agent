"""Tests for OllamaClient — native Ollama /api/chat endpoint via httpx.

Covers:
- Client construction
- Auth headers: empty for HTTP, Bearer token for HTTPS
- generate() happy path and error mapping (auth, timeout, API, empty)
- generate_stream() happy path and error mapping
- Factory: returns OllamaClient when OLLAMA_BASE_URL is set
- Factory: raises LLMConfigError when OLLAMA_BASE_URL is absent
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from taskorbit.config import Settings, get_settings
from taskorbit.integrations.llm.errors import (
    LLMAPIError,
    LLMAuthError,
    LLMConfigError,
    LLMTimeoutError,
)
from taskorbit.integrations.llm.factory import get_llm_client
from taskorbit.integrations.llm.ollama_client import OllamaClient
from taskorbit.types import LLMConfig, LLMProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HTTP_URL = "http://localhost:11434"
_HTTPS_URL = "https://taskorbit-ollama-abc123-ew.a.run.app"
_MODEL = "gemma4:26b"


def _make_settings(base_url: str = _HTTP_URL, model: str = _MODEL) -> Settings:
    return Settings(ollama_base_url=base_url, ollama_model=model)


def _make_llm_config(model: str = _MODEL) -> LLMConfig:
    return LLMConfig(provider=LLMProvider.OLLAMA, model=model)


def _make_httpx_response(content: str, status_code: int = 200) -> MagicMock:
    """Return a mock httpx.Response with native Ollama /api/chat JSON body."""
    body = {"message": {"role": "assistant", "content": content}, "done": True}
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp


def _make_httpx_error_response(status_code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", _HTTP_URL)
    resp = httpx.Response(status_code=status_code, request=req)
    return httpx.HTTPStatusError("error", request=req, response=resp)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_ollama_client_strips_trailing_slash() -> None:
    settings = _make_settings(base_url="http://localhost:11434/")
    client = OllamaClient(llm_config=_make_llm_config(), settings=settings)
    assert client._base_url == "http://localhost:11434"


def test_ollama_client_needs_auth_false_by_default() -> None:
    client = OllamaClient(llm_config=_make_llm_config(), settings=_make_settings())
    assert client._needs_auth is False


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_headers_empty_when_needs_auth_false() -> None:
    client = OllamaClient(llm_config=_make_llm_config(), settings=_make_settings())
    assert await client._auth_headers() == {}


@pytest.mark.asyncio
async def test_auth_headers_returns_bearer_token_when_auth_enabled() -> None:
    client = OllamaClient(llm_config=_make_llm_config(), settings=_make_settings())
    client._needs_auth = True
    with patch(
        "taskorbit.integrations.llm.ollama_client._get_identity_token",
        new=AsyncMock(return_value="id-token-xyz"),
    ):
        headers = await client._auth_headers()
    assert headers == {"Authorization": "Bearer id-token-xyz"}


# ---------------------------------------------------------------------------
# verify_model_available() — model tag preflight check
# ---------------------------------------------------------------------------


def _make_tags_response(*model_names: str) -> MagicMock:
    """Mock httpx.Response for GET /api/tags."""
    body = {"models": [{"name": name} for name in model_names]}
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_verify_model_available_returns_tags_when_present() -> None:
    client = OllamaClient(llm_config=_make_llm_config(), settings=_make_settings())
    client._http = AsyncMock()
    client._http.get = AsyncMock(return_value=_make_tags_response(_MODEL, "qwen3.6:27b"))
    available = await client.verify_model_available()
    assert _MODEL in available


@pytest.mark.asyncio
async def test_verify_model_available_raises_config_error_when_missing() -> None:
    """A configured tag absent from the endpoint must fail with a clear error."""
    client = OllamaClient(llm_config=_make_llm_config(), settings=_make_settings())
    client._http = AsyncMock()
    client._http.get = AsyncMock(
        return_value=_make_tags_response("qwen3.6:27b")
    )  # _MODEL not present
    with pytest.raises(LLMConfigError) as exc:
        await client.verify_model_available()
    assert _MODEL in str(exc.value)
    assert "ollama pull" in str(exc.value)


@pytest.mark.asyncio
async def test_verify_model_available_raises_config_error_when_endpoint_empty() -> None:
    client = OllamaClient(llm_config=_make_llm_config(), settings=_make_settings())
    client._http = AsyncMock()
    client._http.get = AsyncMock(return_value=_make_tags_response())  # no models loaded
    with pytest.raises(LLMConfigError):
        await client.verify_model_available()


@pytest.mark.asyncio
async def test_verify_model_available_maps_api_error() -> None:
    client = OllamaClient(llm_config=_make_llm_config(), settings=_make_settings())
    client._http = AsyncMock()
    client._http.get = AsyncMock(side_effect=_make_httpx_error_response(500))
    with pytest.raises(LLMAPIError):
        await client.verify_model_available()


# ---------------------------------------------------------------------------
# generate() — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_returns_text() -> None:
    settings = _make_settings()
    llm_config = _make_llm_config()
    client = OllamaClient(llm_config=llm_config, settings=settings)
    client._http = AsyncMock()
    client._http.post = AsyncMock(return_value=_make_httpx_response("Gemma says hello"))

    result = await client.generate("You are helpful.", [], llm_config)
    assert result == "Gemma says hello"


@pytest.mark.asyncio
async def test_generate_passes_model_and_think_false() -> None:
    settings = _make_settings()
    llm_config = _make_llm_config(model="qwen3.6:27b")
    client = OllamaClient(llm_config=llm_config, settings=settings)
    client._http = AsyncMock()
    client._http.post = AsyncMock(return_value=_make_httpx_response("Qwen reply"))

    await client.generate("sys", [], llm_config)

    call_kwargs = client._http.post.call_args.kwargs
    assert call_kwargs["json"]["model"] == "qwen3.6:27b"
    assert call_kwargs["json"]["think"] is False
    assert call_kwargs["json"]["stream"] is False


@pytest.mark.asyncio
async def test_generate_sends_system_prompt_as_first_message() -> None:
    settings = _make_settings()
    llm_config = _make_llm_config()
    client = OllamaClient(llm_config=llm_config, settings=settings)
    client._http = AsyncMock()
    client._http.post = AsyncMock(return_value=_make_httpx_response("ok"))

    await client.generate("Be concise.", [], llm_config)

    messages = client._http.post.call_args.kwargs["json"]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "Be concise."


# ---------------------------------------------------------------------------
# generate() — error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_raises_llm_auth_error_on_401() -> None:
    client = OllamaClient(llm_config=_make_llm_config(), settings=_make_settings())
    client._http = AsyncMock()
    client._http.post = AsyncMock(side_effect=_make_httpx_error_response(401))

    with pytest.raises(LLMAuthError):
        await client.generate("sys", [], _make_llm_config())


@pytest.mark.asyncio
async def test_generate_raises_llm_api_error_on_500() -> None:
    client = OllamaClient(llm_config=_make_llm_config(), settings=_make_settings())
    client._http = AsyncMock()
    client._http.post = AsyncMock(side_effect=_make_httpx_error_response(500))

    with pytest.raises(LLMAPIError):
        await client.generate("sys", [], _make_llm_config())


@pytest.mark.asyncio
async def test_generate_raises_llm_timeout_error() -> None:
    client = OllamaClient(llm_config=_make_llm_config(), settings=_make_settings())
    client._http = AsyncMock()
    client._http.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    with pytest.raises(LLMTimeoutError):
        await client.generate("sys", [], _make_llm_config())


@pytest.mark.asyncio
async def test_generate_raises_llm_api_error_on_empty_content() -> None:
    client = OllamaClient(llm_config=_make_llm_config(), settings=_make_settings())
    client._http = AsyncMock()
    empty_resp = MagicMock(spec=httpx.Response)
    empty_resp.json.return_value = {"message": {"role": "assistant", "content": ""}, "done": True}
    empty_resp.raise_for_status = MagicMock()
    client._http.post = AsyncMock(return_value=empty_resp)

    with pytest.raises(LLMAPIError, match="empty response"):
        await client.generate("sys", [], _make_llm_config())


# ---------------------------------------------------------------------------
# generate_stream()
# ---------------------------------------------------------------------------


class _FakeStreamContext:
    """Minimal async context manager + line iterator for httpx streaming."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line


@pytest.mark.asyncio
async def test_generate_stream_yields_tokens() -> None:
    client = OllamaClient(llm_config=_make_llm_config(), settings=_make_settings())

    lines = [
        json.dumps({"message": {"content": "Hello"}, "done": False}),
        json.dumps({"message": {"content": " world"}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True}),
    ]
    fake_ctx = _FakeStreamContext(lines)
    client._http = MagicMock()
    client._http.stream = MagicMock(return_value=fake_ctx)

    tokens = []
    async for token in client.generate_stream("sys", [], _make_llm_config()):
        tokens.append(token)

    assert tokens == ["Hello", " world"]


@pytest.mark.asyncio
async def test_generate_stream_raises_timeout_error() -> None:
    client = OllamaClient(llm_config=_make_llm_config(), settings=_make_settings())

    class _TimeoutCtx:
        async def __aenter__(self):
            raise httpx.TimeoutException("timed out")

        async def __aexit__(self, *args):
            pass

    client._http = MagicMock()
    client._http.stream = MagicMock(return_value=_TimeoutCtx())

    with pytest.raises(LLMTimeoutError):
        async for _ in client.generate_stream("sys", [], _make_llm_config()):
            pass


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


def test_get_llm_client_returns_ollama_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", _HTTP_URL)
    monkeypatch.setenv("OLLAMA_MODEL", _MODEL)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        client = get_llm_client(_make_llm_config(), settings=settings)
        assert isinstance(client, OllamaClient)
    finally:
        get_settings.cache_clear()


def test_get_llm_client_raises_when_ollama_base_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        with pytest.raises(LLMConfigError, match="OLLAMA_BASE_URL"):
            get_llm_client(_make_llm_config(), settings=settings)
    finally:
        get_settings.cache_clear()
