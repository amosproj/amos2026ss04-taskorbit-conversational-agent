"""Tests for OpenRouterClient and the factory wiring for LLMProvider.OPENROUTER.

Covers:
- Client construction: correct base_url, api_key, required headers
- generate() happy path and error mapping
- generate_stream() happy path
- Factory: returns OpenRouterClient for OPENROUTER provider
- Factory: raises LLMConfigError when OPENROUTER_API_KEY is absent
- Guard: _guard_provider_model_match does not raise for openrouter + free-form model name
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.config import get_settings
from taskorbit.integrations.llm.errors import LLMAuthError, LLMConfigError, LLMRateLimitError
from taskorbit.integrations.llm.factory import _guard_provider_model_match, get_llm_client
from taskorbit.integrations.llm.openrouter_client import _OPENROUTER_BASE_URL, OpenRouterClient
from taskorbit.types import LLMConfig, LLMProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def openrouter_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _make_llm_config(model: str = "qwen/qwen-2.5-7b-instruct:free") -> LLMConfig:
    return LLMConfig(provider=LLMProvider.OPENROUTER, model=model)


def _make_completion_response(text: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = text
    response = MagicMock()
    response.choices = [choice]
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 20
    return response


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_openrouter_client_uses_correct_base_url(openrouter_settings: None) -> None:
    settings = get_settings()
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.openrouter_client.openai.AsyncOpenAI") as mock_cls:
        OpenRouterClient(llm_config=llm_config, settings=settings)
    mock_cls.assert_called_once()
    assert mock_cls.call_args.kwargs["base_url"] == _OPENROUTER_BASE_URL


def test_openrouter_client_uses_api_key_from_settings(openrouter_settings: None) -> None:
    settings = get_settings()
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.openrouter_client.openai.AsyncOpenAI") as mock_cls:
        OpenRouterClient(llm_config=llm_config, settings=settings)
    assert mock_cls.call_args.kwargs["api_key"] == "sk-or-test-key"


def test_openrouter_client_sends_required_headers(openrouter_settings: None) -> None:
    settings = get_settings()
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.openrouter_client.openai.AsyncOpenAI") as mock_cls:
        OpenRouterClient(llm_config=llm_config, settings=settings)
    headers = mock_cls.call_args.kwargs["default_headers"]
    assert "HTTP-Referer" in headers
    assert "X-Title" in headers


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openrouter_client_generate_returns_text(openrouter_settings: None) -> None:
    settings = get_settings()
    llm_config = _make_llm_config()
    fake_response = _make_completion_response("Hello from Qwen!")

    with patch("taskorbit.integrations.llm.openrouter_client.openai.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_response)
        mock_cls.return_value = mock_client

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        result = await client.generate("You are helpful.", [], llm_config)

    assert result == "Hello from Qwen!"


@pytest.mark.asyncio
async def test_openrouter_client_generate_raises_llm_auth_error(openrouter_settings: None) -> None:
    import openai as _openai

    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.openai.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=_openai.AuthenticationError("bad key", response=MagicMock(), body={})
        )
        mock_cls.return_value = mock_client

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAuthError):
            await client.generate("You are helpful.", [], llm_config)


@pytest.mark.asyncio
async def test_openrouter_client_generate_raises_llm_rate_limit_error(
    openrouter_settings: None,
) -> None:
    import openai as _openai

    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.openai.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=_openai.RateLimitError("rate limited", response=MagicMock(), body={})
        )
        mock_cls.return_value = mock_client

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMRateLimitError):
            await client.generate("You are helpful.", [], llm_config)


@pytest.mark.asyncio
async def test_openrouter_client_generate_raises_llm_timeout_error(
    openrouter_settings: None,
) -> None:
    import openai as _openai

    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.openai.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=_openai.APITimeoutError(request=MagicMock())
        )
        mock_cls.return_value = mock_client

        from taskorbit.integrations.llm.errors import LLMTimeoutError

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMTimeoutError):
            await client.generate("You are helpful.", [], llm_config)


@pytest.mark.asyncio
async def test_openrouter_client_generate_raises_llm_api_error(
    openrouter_settings: None,
) -> None:
    import openai as _openai

    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.openai.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=_openai.APIError("server error", request=MagicMock(), body={})
        )
        mock_cls.return_value = mock_client

        from taskorbit.integrations.llm.errors import LLMAPIError

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAPIError):
            await client.generate("You are helpful.", [], llm_config)


@pytest.mark.asyncio
async def test_openrouter_client_generate_raises_on_empty_response(
    openrouter_settings: None,
) -> None:
    settings = get_settings()
    llm_config = _make_llm_config()
    empty_response = MagicMock()
    empty_response.choices = []

    with patch("taskorbit.integrations.llm.openrouter_client.openai.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=empty_response)
        mock_cls.return_value = mock_client

        from taskorbit.integrations.llm.errors import LLMAPIError

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAPIError):
            await client.generate("You are helpful.", [], llm_config)


# ---------------------------------------------------------------------------
# generate_stream()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openrouter_client_generate_stream_yields_tokens(openrouter_settings: None) -> None:
    settings = get_settings()
    llm_config = _make_llm_config()

    async def _chunks() -> AsyncIterator[Any]:
        for token in ["Hello", " from", " Gemma"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = token
            chunk.usage = None
            yield chunk

    class _FakeStream:
        def __aiter__(self) -> AsyncIterator[Any]:
            return _chunks()

        async def close(self) -> None:
            pass

    with patch("taskorbit.integrations.llm.openrouter_client.openai.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_FakeStream())
        mock_cls.return_value = mock_client

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        tokens = []
        async for token in client.generate_stream("You are helpful.", [], llm_config):
            tokens.append(token)

    assert tokens == ["Hello", " from", " Gemma"]


@pytest.mark.asyncio
async def test_openrouter_client_generate_stream_raises_auth_error(
    openrouter_settings: None,
) -> None:
    import openai as _openai

    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.openai.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=_openai.AuthenticationError("bad key", response=MagicMock(), body={})
        )
        mock_cls.return_value = mock_client

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAuthError):
            async for _ in client.generate_stream("You are helpful.", [], llm_config):
                pass


@pytest.mark.asyncio
async def test_openrouter_client_generate_stream_raises_rate_limit_error(
    openrouter_settings: None,
) -> None:
    import openai as _openai

    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.openai.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=_openai.RateLimitError("rate limited", response=MagicMock(), body={})
        )
        mock_cls.return_value = mock_client

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMRateLimitError):
            async for _ in client.generate_stream("You are helpful.", [], llm_config):
                pass


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


def test_get_llm_client_returns_openrouter_client(openrouter_settings: None) -> None:
    settings = get_settings()
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.openrouter_client.openai.AsyncOpenAI"):
        client = get_llm_client(llm_config, settings=settings)
    assert isinstance(client, OpenRouterClient)


def test_get_llm_client_raises_when_openrouter_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        llm_config = _make_llm_config()
        with pytest.raises(LLMConfigError, match="OPENROUTER_API_KEY"):
            get_llm_client(llm_config, settings=settings)
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Provider/model guard
# ---------------------------------------------------------------------------


def test_guard_does_not_raise_for_openrouter_with_free_model() -> None:
    """Namespaced free-tier model names must not trigger the prefix guard."""
    for model in [
        "qwen/qwen-2.5-7b-instruct:free",
        "google/gemma-3-12b-it:free",
        "meta-llama/llama-3.1-8b-instruct:free",
        "deepseek/deepseek-r1:free",
        "mistralai/mistral-7b-instruct:free",
    ]:
        _guard_provider_model_match(LLMConfig(provider=LLMProvider.OPENROUTER, model=model))


def test_guard_does_not_raise_for_openrouter_with_paid_model() -> None:
    """Paid OpenRouter models (no :free suffix) must also pass."""
    _guard_provider_model_match(
        LLMConfig(provider=LLMProvider.OPENROUTER, model="anthropic/claude-3-haiku")
    )
