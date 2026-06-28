"""Tests for OllamaClient and factory wiring for LLMProvider.OLLAMA.

Covers:
- _is_https() utility
- Client construction: base_url and api_key forwarded to the SDK
- HTTPS URL triggers GCP identity token auth; HTTP skips it
- generate() happy path and error mapping (auth, timeout, API, empty)
- generate_stream() happy path and auth error
- Factory: returns OllamaClient when OLLAMA_BASE_URL is set
- Factory: raises LLMConfigError when OLLAMA_BASE_URL is absent
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from taskorbit.config import Settings, get_settings
from taskorbit.integrations.llm.errors import (
    LLMAPIError,
    LLMAuthError,
    LLMConfigError,
    LLMTimeoutError,
)
from taskorbit.integrations.llm.factory import get_llm_client
from taskorbit.integrations.llm.ollama_client import OllamaClient, _is_https
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


def _make_sdk_response(text: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = text
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage.prompt_tokens = 15
    resp.usage.completion_tokens = 30
    return resp


def _make_stream_chunk(text: str | None) -> MagicMock:
    chunk = MagicMock()
    if text is not None:
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = text
    else:
        chunk.choices = []
    return chunk


# ---------------------------------------------------------------------------
# _is_https utility
# ---------------------------------------------------------------------------


def test_is_https_returns_true_for_https_url() -> None:
    assert _is_https("https://example.a.run.app") is True


def test_is_https_returns_false_for_http_url() -> None:
    assert _is_https("http://localhost:11434") is False


def test_is_https_returns_false_for_empty_string() -> None:
    assert _is_https("") is False


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_ollama_client_sets_base_url_with_v1_suffix() -> None:
    settings = _make_settings(base_url=_HTTP_URL)
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        OllamaClient(llm_config=llm_config, settings=settings)
    mock_cls.assert_called_once()
    assert mock_cls.call_args.kwargs["base_url"] == f"{_HTTP_URL}/v1"


def test_ollama_client_uses_placeholder_api_key() -> None:
    """Ollama ignores the api_key; we use "ollama" to satisfy the SDK."""
    settings = _make_settings()
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        OllamaClient(llm_config=llm_config, settings=settings)
    assert mock_cls.call_args.kwargs["api_key"] == "ollama"


def test_ollama_client_strips_trailing_slash_from_base_url() -> None:
    settings = _make_settings(base_url="http://localhost:11434/")
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        OllamaClient(llm_config=llm_config, settings=settings)
    assert mock_cls.call_args.kwargs["base_url"] == "http://localhost:11434/v1"


def test_ollama_client_needs_auth_false_for_http() -> None:
    settings = _make_settings(base_url=_HTTP_URL)
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI"):
        client = OllamaClient(llm_config=llm_config, settings=settings)
    assert client._needs_auth is False


def test_ollama_client_needs_auth_true_for_https() -> None:
    settings = _make_settings(base_url=_HTTPS_URL)
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI"):
        client = OllamaClient(llm_config=llm_config, settings=settings)
    assert client._needs_auth is True


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_headers_empty_for_http_url() -> None:
    settings = _make_settings(base_url=_HTTP_URL)
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI"):
        client = OllamaClient(llm_config=llm_config, settings=settings)
    headers = await client._auth_headers()
    assert headers == {}


@pytest.mark.asyncio
async def test_auth_headers_returns_bearer_token_for_https() -> None:
    settings = _make_settings(base_url=_HTTPS_URL)
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI"):
        client = OllamaClient(llm_config=llm_config, settings=settings)

    with patch(
        "taskorbit.integrations.llm.ollama_client._get_identity_token",
        new=AsyncMock(return_value="id-token-xyz"),
    ):
        headers = await client._auth_headers()

    assert headers == {"Authorization": "Bearer id-token-xyz"}


@pytest.mark.asyncio
async def test_get_identity_token_raises_llm_auth_error_when_not_on_gcp() -> None:
    from taskorbit.integrations.llm.ollama_client import _get_identity_token

    with patch(
        "taskorbit.integrations.llm.ollama_client._get_identity_token",
        new=AsyncMock(side_effect=LLMAuthError("metadata server unreachable")),
    ):
        with pytest.raises(LLMAuthError):
            await _get_identity_token("https://example.a.run.app")


# ---------------------------------------------------------------------------
# verify_model_available() — model tag preflight check
# ---------------------------------------------------------------------------


def _make_models_listing(*model_ids: str) -> MagicMock:
    """Mock an openai client.models.list() response with the given model ids."""
    listing = MagicMock()
    listing.data = [MagicMock(id=mid) for mid in model_ids]
    return listing


def _client_with_listing(listing: MagicMock, base_url: str = _HTTP_URL) -> OllamaClient:
    settings = _make_settings(base_url=base_url)
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        mock_openai = MagicMock()
        mock_openai.models.list = AsyncMock(return_value=listing)
        mock_cls.return_value = mock_openai
        return OllamaClient(llm_config=llm_config, settings=settings)


@pytest.mark.asyncio
async def test_verify_model_available_returns_tags_when_present() -> None:
    listing = _make_models_listing(_MODEL, "qwen3.6:27b")
    client = _client_with_listing(listing)
    available = await client.verify_model_available()
    assert _MODEL in available


@pytest.mark.asyncio
async def test_verify_model_available_raises_config_error_when_missing() -> None:
    """A configured tag absent from the endpoint must fail with a clear error."""
    listing = _make_models_listing("qwen3.6:27b")  # _MODEL not present
    client = _client_with_listing(listing)
    with pytest.raises(LLMConfigError) as exc:
        await client.verify_model_available()
    assert _MODEL in str(exc.value)
    assert "ollama pull" in str(exc.value)


@pytest.mark.asyncio
async def test_verify_model_available_raises_config_error_when_endpoint_empty() -> None:
    listing = _make_models_listing()  # no models loaded at all
    client = _client_with_listing(listing)
    with pytest.raises(LLMConfigError):
        await client.verify_model_available()


@pytest.mark.asyncio
async def test_verify_model_available_maps_api_error() -> None:
    settings = _make_settings(base_url=_HTTP_URL)
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        mock_openai = MagicMock()
        mock_openai.models.list = AsyncMock(
            side_effect=openai.APIError("boom", request=MagicMock(), body=None)
        )
        mock_cls.return_value = mock_openai
        client = OllamaClient(llm_config=llm_config, settings=settings)
    with pytest.raises(LLMAPIError):
        await client.verify_model_available()


# ---------------------------------------------------------------------------
# generate() — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_returns_text_for_http_url() -> None:
    settings = _make_settings(base_url=_HTTP_URL)
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(
            return_value=_make_sdk_response("Gemma says hello")
        )
        mock_cls.return_value = mock_openai

        client = OllamaClient(llm_config=llm_config, settings=settings)
        result = await client.generate("You are helpful.", [], llm_config)

    assert result == "Gemma says hello"


@pytest.mark.asyncio
async def test_generate_passes_model_from_llm_config() -> None:
    settings = _make_settings(base_url=_HTTP_URL)
    llm_config = _make_llm_config(model="qwen3.6:27b")

    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(
            return_value=_make_sdk_response("Qwen reply")
        )
        mock_cls.return_value = mock_openai

        client = OllamaClient(llm_config=llm_config, settings=settings)
        await client.generate("sys", [], llm_config)

    call_kwargs = mock_openai.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "qwen3.6:27b"


@pytest.mark.asyncio
async def test_generate_sends_auth_header_for_https_url() -> None:
    settings = _make_settings(base_url=_HTTPS_URL)
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(
            return_value=_make_sdk_response("secure reply")
        )
        mock_cls.return_value = mock_openai

        with patch(
            "taskorbit.integrations.llm.ollama_client._get_identity_token",
            new=AsyncMock(return_value="my-gcp-token"),
        ):
            client = OllamaClient(llm_config=llm_config, settings=settings)
            await client.generate("sys", [], llm_config)

    call_kwargs = mock_openai.chat.completions.create.call_args.kwargs
    assert call_kwargs["extra_headers"] == {"Authorization": "Bearer my-gcp-token"}


# ---------------------------------------------------------------------------
# generate() — error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_raises_llm_auth_error_on_401() -> None:
    settings = _make_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=openai.AuthenticationError("bad key", response=MagicMock(), body={})
        )
        mock_cls.return_value = mock_openai

        client = OllamaClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAuthError):
            await client.generate("sys", [], llm_config)


@pytest.mark.asyncio
async def test_generate_raises_llm_timeout_error() -> None:
    settings = _make_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=openai.APITimeoutError(request=MagicMock())
        )
        mock_cls.return_value = mock_openai

        client = OllamaClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMTimeoutError):
            await client.generate("sys", [], llm_config)


@pytest.mark.asyncio
async def test_generate_raises_llm_api_error_on_generic_api_error() -> None:
    settings = _make_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=openai.APIError("server error", request=MagicMock(), body={})
        )
        mock_cls.return_value = mock_openai

        client = OllamaClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAPIError):
            await client.generate("sys", [], llm_config)


@pytest.mark.asyncio
async def test_generate_raises_llm_api_error_on_empty_response() -> None:
    settings = _make_settings()
    llm_config = _make_llm_config()

    empty = MagicMock()
    empty.choices = []

    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(return_value=empty)
        mock_cls.return_value = mock_openai

        client = OllamaClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAPIError, match="empty response"):
            await client.generate("sys", [], llm_config)


# ---------------------------------------------------------------------------
# generate_stream()
# ---------------------------------------------------------------------------


class _FakeStream:
    """Minimal async iterable with a close() method matching the openai SDK's AsyncStream."""

    def __init__(self, chunks: list) -> None:
        self._chunks = chunks

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for c in self._chunks:
            yield c

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_generate_stream_yields_tokens() -> None:
    settings = _make_settings(base_url=_HTTP_URL)
    llm_config = _make_llm_config()

    chunks = [_make_stream_chunk("Hello"), _make_stream_chunk(" world"), _make_stream_chunk(None)]

    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(return_value=_FakeStream(chunks))
        mock_cls.return_value = mock_openai

        client = OllamaClient(llm_config=llm_config, settings=settings)
        tokens = []
        async for token in client.generate_stream("sys", [], llm_config):
            tokens.append(token)

    assert tokens == ["Hello", " world"]


@pytest.mark.asyncio
async def test_generate_stream_raises_auth_error_on_connection_failure() -> None:
    settings = _make_settings(base_url=_HTTP_URL)
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI") as mock_cls:
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=openai.AuthenticationError("bad key", response=MagicMock(), body={})
        )
        mock_cls.return_value = mock_openai

        client = OllamaClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAuthError):
            async for _ in client.generate_stream("sys", [], llm_config):
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
        llm_config = _make_llm_config()
        with patch("taskorbit.integrations.llm.ollama_client.openai.AsyncOpenAI"):
            client = get_llm_client(llm_config, settings=settings)
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
        llm_config = _make_llm_config()
        with pytest.raises(LLMConfigError, match="OLLAMA_BASE_URL"):
            get_llm_client(llm_config, settings=settings)
    finally:
        get_settings.cache_clear()
