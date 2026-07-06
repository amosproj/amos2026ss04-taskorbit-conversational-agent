"""Tests for OpenRouterClient and the factory wiring for LLMProvider.OPENROUTER.

Covers:
- Client construction: api_key forwarded to the SDK
- generate() happy path and error mapping
- generate_stream() happy path (delegates to generate())
- Factory: returns OpenRouterClient for OPENROUTER provider
- Factory: raises LLMConfigError when OPENROUTER_API_KEY is absent
- Guard: _guard_provider_model_match does not raise for openrouter + free-form model name
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.config import get_settings
from taskorbit.integrations.llm.errors import (
    LLMAPIError,
    LLMAuthError,
    LLMConfigError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from taskorbit.integrations.llm.factory import _guard_provider_model_match, get_llm_client
from taskorbit.integrations.llm.openrouter_client import OpenRouterClient
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


def _make_sdk_response(text: str) -> MagicMock:
    """Build a minimal ChatResult-like mock."""
    choice = MagicMock()
    choice.message.content = text
    result = MagicMock()
    result.choices = [choice]
    result.usage.prompt_tokens = 10
    result.usage.completion_tokens = 20
    return result


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_openrouter_client_passes_api_key_to_sdk(openrouter_settings: None) -> None:
    settings = get_settings()
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
        OpenRouterClient(llm_config=llm_config, settings=settings)
    mock_cls.assert_called_once()
    assert mock_cls.call_args.kwargs["api_key"] == "sk-or-test-key"


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openrouter_client_generate_returns_text(openrouter_settings: None) -> None:
    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
        mock_sdk = MagicMock()
        mock_sdk.chat.send_async = AsyncMock(return_value=_make_sdk_response("Hello from Qwen!"))
        mock_cls.return_value = mock_sdk

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        result = await client.generate("You are helpful.", [], llm_config)

    assert result == "Hello from Qwen!"


@pytest.mark.asyncio
async def test_openrouter_client_generate_raises_llm_auth_error(openrouter_settings: None) -> None:
    from openrouter.errors import ForbiddenResponseError

    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
        mock_sdk = MagicMock()
        # ForbiddenResponseError(data, raw_response, body=None)
        mock_sdk.chat.send_async = AsyncMock(
            side_effect=ForbiddenResponseError(MagicMock(), MagicMock())
        )
        mock_cls.return_value = mock_sdk

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAuthError):
            await client.generate("You are helpful.", [], llm_config)


@pytest.mark.asyncio
async def test_openrouter_client_generate_raises_llm_auth_error_on_unauthorized_response(
    openrouter_settings: None,
) -> None:
    """Invalid or revoked API keys surface as UnauthorizedResponseError from
    the SDK and must map to LLMAuthError so the orchestrator returns the
    auth-specific user message (#197)."""
    from openrouter.errors import UnauthorizedResponseError

    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
        mock_sdk = MagicMock()
        mock_sdk.chat.send_async = AsyncMock(
            side_effect=UnauthorizedResponseError(MagicMock(), MagicMock())
        )
        mock_cls.return_value = mock_sdk

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAuthError):
            await client.generate("You are helpful.", [], llm_config)


@pytest.mark.asyncio
async def test_openrouter_client_generate_raises_llm_rate_limit_error_on_too_many_requests(
    openrouter_settings: None,
) -> None:
    """OpenRouter's own 429 throttling surfaces as TooManyRequestsResponseError
    and must map to LLMRateLimitError so the orchestrator returns the
    rate-limit-specific user message (#197)."""
    from openrouter.errors import TooManyRequestsResponseError

    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
        mock_sdk = MagicMock()
        mock_sdk.chat.send_async = AsyncMock(
            side_effect=TooManyRequestsResponseError(MagicMock(), MagicMock())
        )
        mock_cls.return_value = mock_sdk

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMRateLimitError):
            await client.generate("You are helpful.", [], llm_config)


@pytest.mark.asyncio
async def test_openrouter_client_unauthorized_response_increments_auth_metric(
    openrouter_settings: None,
) -> None:
    """UnauthorizedResponseError must increment llm_requests_total with status='auth'
    so Grafana / alerting can distinguish key-invalid from other auth failures (#197)."""
    from openrouter.errors import UnauthorizedResponseError

    settings = get_settings()
    llm_config = _make_llm_config()
    mock_metrics = MagicMock()

    with patch(
        "taskorbit.integrations.llm.openrouter_client.get_metrics", return_value=mock_metrics
    ):
        with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
            mock_sdk = MagicMock()
            mock_sdk.chat.send_async = AsyncMock(
                side_effect=UnauthorizedResponseError(MagicMock(), MagicMock())
            )
            mock_cls.return_value = mock_sdk

            client = OpenRouterClient(llm_config=llm_config, settings=settings)
            with pytest.raises(LLMAuthError):
                await client.generate("You are helpful.", [], llm_config)

    mock_metrics.llm_requests_total.labels.assert_any_call(
        provider="openrouter", model=llm_config.model, status="auth"
    )


@pytest.mark.asyncio
async def test_openrouter_client_too_many_requests_uses_body_and_increments_rate_limit_metric(
    openrouter_settings: None,
) -> None:
    """TooManyRequestsResponseError.body carries the actual reason; the client must
    copy it into the raised LLMRateLimitError (#197) and emit status='rate_limit'."""
    from openrouter.errors import TooManyRequestsResponseError

    settings = get_settings()
    llm_config = _make_llm_config()
    mock_metrics = MagicMock()

    tm_exc = TooManyRequestsResponseError(MagicMock(), MagicMock())
    tm_exc.body = "rate limit exceeded, retry after 30s"

    with patch(
        "taskorbit.integrations.llm.openrouter_client.get_metrics", return_value=mock_metrics
    ):
        with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
            mock_sdk = MagicMock()
            mock_sdk.chat.send_async = AsyncMock(side_effect=tm_exc)
            mock_cls.return_value = mock_sdk

            client = OpenRouterClient(llm_config=llm_config, settings=settings)
            with pytest.raises(LLMRateLimitError, match="rate limit exceeded"):
                await client.generate("You are helpful.", [], llm_config)

    mock_metrics.llm_requests_total.labels.assert_any_call(
        provider="openrouter", model=llm_config.model, status="rate_limit"
    )


@pytest.mark.asyncio
async def test_openrouter_client_openrouter_error_uses_body_when_available(
    openrouter_settings: None,
) -> None:
    """Generic OpenRouterError.body must be used in the raised LLMAPIError message
    when populated, so the operator sees the real upstream reason rather than the
    SDK's generic 'Provider returned error'."""
    from openrouter.errors import OpenRouterError

    settings = get_settings()
    llm_config = _make_llm_config()

    api_exc = OpenRouterError("api error", MagicMock())
    api_exc.body = "upstream returned 502 bad gateway from anthropic"

    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
        mock_sdk = MagicMock()
        mock_sdk.chat.send_async = AsyncMock(side_effect=api_exc)
        mock_cls.return_value = mock_sdk

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAPIError, match="upstream returned 502 bad gateway"):
            await client.generate("You are helpful.", [], llm_config)


@pytest.mark.asyncio
async def test_openrouter_client_bounded_detail_truncates_large_bodies(
    openrouter_settings: None,
) -> None:
    """_bounded_detail must cap exc.body at 500 chars so an oversized upstream
    response body cannot bloat logs or the user-visible LLMError message."""
    from openrouter.errors import OpenRouterError

    settings = get_settings()
    llm_config = _make_llm_config()

    huge_body = "x" * 2000
    api_exc = OpenRouterError("api error", MagicMock())
    api_exc.body = huge_body

    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
        mock_sdk = MagicMock()
        mock_sdk.chat.send_async = AsyncMock(side_effect=api_exc)
        mock_cls.return_value = mock_sdk

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAPIError) as excinfo:
            await client.generate("You are helpful.", [], llm_config)

    raised_msg = str(excinfo.value)
    assert "[truncated]" in raised_msg
    # Bound: 500 chars of body + a prefix and the truncation marker; nowhere near 2000.
    assert len(raised_msg) < 800, f"expected truncation, got {len(raised_msg)} char message"


@pytest.mark.asyncio
async def test_openrouter_client_generate_raises_llm_rate_limit_error_on_provider_overloaded(
    openrouter_settings: None,
) -> None:
    """Upstream provider throttling on :free-tier models surfaces as
    ProviderOverloadedResponseError. The body carries the actual reason
    (str(exc) is a generic "Provider returned error"), so the client copies
    exc.body into the raised LLMRateLimitError message for diagnosability (#197)."""
    from openrouter.errors import ProviderOverloadedResponseError

    settings = get_settings()
    llm_config = _make_llm_config()

    overloaded_exc = ProviderOverloadedResponseError(MagicMock(), MagicMock())
    overloaded_exc.body = "upstream provider is currently overloaded, please retry"

    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
        mock_sdk = MagicMock()
        mock_sdk.chat.send_async = AsyncMock(side_effect=overloaded_exc)
        mock_cls.return_value = mock_sdk

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMRateLimitError, match="overloaded"):
            await client.generate("You are helpful.", [], llm_config)


@pytest.mark.asyncio
async def test_openrouter_client_generate_raises_llm_timeout_error(
    openrouter_settings: None,
) -> None:
    from openrouter.errors import EdgeNetworkTimeoutResponseError

    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
        mock_sdk = MagicMock()
        # EdgeNetworkTimeoutResponseError(data, raw_response, body=None)
        mock_sdk.chat.send_async = AsyncMock(
            side_effect=EdgeNetworkTimeoutResponseError(MagicMock(), MagicMock())
        )
        mock_cls.return_value = mock_sdk

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMTimeoutError):
            await client.generate("You are helpful.", [], llm_config)


@pytest.mark.asyncio
async def test_openrouter_client_generate_raises_llm_api_error_on_openrouter_error(
    openrouter_settings: None,
) -> None:
    from openrouter.errors import OpenRouterError

    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
        mock_sdk = MagicMock()
        # OpenRouterError(message, raw_response, body=None)
        mock_sdk.chat.send_async = AsyncMock(side_effect=OpenRouterError("api error", MagicMock()))
        mock_cls.return_value = mock_sdk

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAPIError):
            await client.generate("You are helpful.", [], llm_config)


@pytest.mark.asyncio
async def test_openrouter_client_generate_raises_on_empty_response(
    openrouter_settings: None,
) -> None:
    settings = get_settings()
    llm_config = _make_llm_config()

    empty_result = MagicMock()
    empty_result.choices = []

    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
        mock_sdk = MagicMock()
        mock_sdk.chat.send_async = AsyncMock(return_value=empty_result)
        mock_cls.return_value = mock_sdk

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAPIError):
            await client.generate("You are helpful.", [], llm_config)


# ---------------------------------------------------------------------------
# generate_stream()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openrouter_client_generate_stream_yields_tokens(openrouter_settings: None) -> None:
    # generate_stream delegates to generate() so it yields one chunk with the full text.
    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
        mock_sdk = MagicMock()
        mock_sdk.chat.send_async = AsyncMock(return_value=_make_sdk_response("Hello from Gemma"))
        mock_cls.return_value = mock_sdk

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        tokens = []
        async for token in client.generate_stream("You are helpful.", [], llm_config):
            tokens.append(token)

    assert tokens == ["Hello from Gemma"]


@pytest.mark.asyncio
async def test_openrouter_client_generate_stream_raises_auth_error(
    openrouter_settings: None,
) -> None:
    from openrouter.errors import ForbiddenResponseError

    settings = get_settings()
    llm_config = _make_llm_config()

    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter") as mock_cls:
        mock_sdk = MagicMock()
        mock_sdk.chat.send_async = AsyncMock(
            side_effect=ForbiddenResponseError(MagicMock(), MagicMock())
        )
        mock_cls.return_value = mock_sdk

        client = OpenRouterClient(llm_config=llm_config, settings=settings)
        with pytest.raises(LLMAuthError):
            async for _ in client.generate_stream("You are helpful.", [], llm_config):
                pass


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


def test_get_llm_client_returns_openrouter_client(openrouter_settings: None) -> None:
    settings = get_settings()
    llm_config = _make_llm_config()
    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter"):
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
