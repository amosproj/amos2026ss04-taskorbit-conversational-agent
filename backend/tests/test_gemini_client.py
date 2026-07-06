"""Unit tests for GeminiClient.

Mocks the google-genai async client so tests never make real network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from google.genai import errors as genai_errors

from taskorbit.config import Settings
from taskorbit.integrations.llm.errors import (
    LLMAPIError,
    LLMAuthError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from taskorbit.integrations.llm.gemini_client import GeminiClient
from taskorbit.types import LLMConfig, LLMProvider, Message, MessageRole


def _make_client() -> GeminiClient:
    """Construct a client with fake credentials for testing."""
    settings = Settings(openai_api_key="", google_api_key="AIza-test-key")
    llm_config = LLMConfig(provider=LLMProvider.GOOGLE, model="gemini-2.5-flash")
    return GeminiClient(llm_config=llm_config, settings=settings)


def _client_error(code: int, message: str = "boom") -> genai_errors.ClientError:
    """Build a ClientError with a status code we can route on."""
    response = MagicMock()
    response.status_code = code
    response.headers = {}
    err = genai_errors.ClientError(code, response_json={"error": {"message": message}})
    err.code = code
    return err


@pytest.fixture
def client() -> GeminiClient:
    return _make_client()


@pytest.fixture
def llm_config() -> LLMConfig:
    return LLMConfig(provider=LLMProvider.GOOGLE, model="gemini-2.5-flash")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_returns_assistant_text(client: GeminiClient, llm_config: LLMConfig) -> None:
    fake_response = MagicMock()
    fake_response.text = "4"
    fake_response.usage_metadata.prompt_token_count = 10
    fake_response.usage_metadata.candidates_token_count = 5
    with patch.object(
        client._client.aio.models, "generate_content", new=AsyncMock(return_value=fake_response)
    ) as mock_create:
        result = await client.generate(
            "You are a helpful assistant.",
            [Message(role=MessageRole.USER, content="What is 2+2?")],
            llm_config,
        )

    assert result == "4"
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "gemini-2.5-flash"
    # System prompt goes into config.system_instruction, not into contents
    assert call_kwargs["config"].system_instruction == "You are a helpful assistant."
    # User message lands in contents as role=user with parts
    assert call_kwargs["contents"] == [{"role": "user", "parts": [{"text": "What is 2+2?"}]}]


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_401_maps_to_llm_auth_error(client: GeminiClient, llm_config: LLMConfig) -> None:
    with patch.object(
        client._client.aio.models, "generate_content", new=AsyncMock(side_effect=_client_error(401))
    ):
        with pytest.raises(LLMAuthError):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


@pytest.mark.asyncio
async def test_403_maps_to_llm_auth_error(client: GeminiClient, llm_config: LLMConfig) -> None:
    with patch.object(
        client._client.aio.models, "generate_content", new=AsyncMock(side_effect=_client_error(403))
    ):
        with pytest.raises(LLMAuthError):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


@pytest.mark.asyncio
async def test_429_maps_to_llm_rate_limit_error(
    client: GeminiClient, llm_config: LLMConfig
) -> None:
    with patch.object(
        client._client.aio.models, "generate_content", new=AsyncMock(side_effect=_client_error(429))
    ):
        with pytest.raises(LLMRateLimitError):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


@pytest.mark.asyncio
async def test_408_maps_to_llm_timeout_error(client: GeminiClient, llm_config: LLMConfig) -> None:
    with patch.object(
        client._client.aio.models, "generate_content", new=AsyncMock(side_effect=_client_error(408))
    ):
        with pytest.raises(LLMTimeoutError):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


@pytest.mark.asyncio
async def test_other_client_error_maps_to_llm_api_error(
    client: GeminiClient, llm_config: LLMConfig
) -> None:
    """4xx codes other than auth/rate-limit/timeout (e.g. 400 Bad Request)."""
    with patch.object(
        client._client.aio.models, "generate_content", new=AsyncMock(side_effect=_client_error(400))
    ):
        with pytest.raises(LLMAPIError):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


@pytest.mark.asyncio
async def test_generic_api_error_maps_to_llm_api_error(
    client: GeminiClient, llm_config: LLMConfig
) -> None:
    """Base APIError catches anything not handled by ClientError (typically 5xx)."""
    response = MagicMock()
    response.headers = {}
    api_exc = genai_errors.APIError(500, response_json={"error": {"message": "boom"}})
    with patch.object(
        client._client.aio.models, "generate_content", new=AsyncMock(side_effect=api_exc)
    ):
        with pytest.raises(LLMAPIError):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


@pytest.mark.asyncio
async def test_unknown_api_response_error_maps_to_llm_api_error(
    client: GeminiClient, llm_config: LLMConfig
) -> None:
    """UnknownApiResponseError inherits from ValueError (not APIError), so it
    slips past `except genai_errors.APIError`. Fires when the SDK cannot parse
    the API response into its known schema (protocol drift, unexpected shape,
    malformed JSON boundary). Regression guard for the parity extension of
    Vineesh's #197 review to Gemini."""
    unknown_exc = genai_errors.UnknownApiResponseError("could not parse response")
    mock_metrics = MagicMock()

    with patch("taskorbit.integrations.llm.gemini_client.get_metrics", return_value=mock_metrics):
        with patch.object(
            client._client.aio.models,
            "generate_content",
            new=AsyncMock(side_effect=unknown_exc),
        ):
            with pytest.raises(LLMAPIError, match="unparseable"):
                await client.generate(
                    "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
                )

    mock_metrics.llm_requests_total.labels.assert_any_call(
        provider="google", model=llm_config.model, status="unknown_response"
    )


# ---------------------------------------------------------------------------
# Empty response handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_text_raises_llm_api_error(client: GeminiClient, llm_config: LLMConfig) -> None:
    fake_response = MagicMock()
    fake_response.text = ""
    with patch.object(
        client._client.aio.models, "generate_content", new=AsyncMock(return_value=fake_response)
    ):
        with pytest.raises(LLMAPIError, match="empty"):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


@pytest.mark.asyncio
async def test_none_text_raises_llm_api_error(client: GeminiClient, llm_config: LLMConfig) -> None:
    """Gemini returns None for blocked responses (safety filter etc.)."""
    fake_response = MagicMock()
    fake_response.text = None
    with patch.object(
        client._client.aio.models, "generate_content", new=AsyncMock(return_value=fake_response)
    ):
        with pytest.raises(LLMAPIError, match="empty"):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


# ---------------------------------------------------------------------------
# Token usage metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_records_token_metrics(client: GeminiClient, llm_config: LLMConfig) -> None:
    fake_response = MagicMock()
    fake_response.text = "4"
    fake_response.usage_metadata.prompt_token_count = 10
    fake_response.usage_metadata.candidates_token_count = 5
    mock_metrics = MagicMock()

    with patch("taskorbit.integrations.llm.gemini_client.get_metrics", return_value=mock_metrics):
        with patch.object(
            client._client.aio.models, "generate_content", new=AsyncMock(return_value=fake_response)
        ):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)

    labels_calls = mock_metrics.tokens_used_total.labels.call_args_list
    assert call(provider="google", model="gemini-2.5-flash", token_type="prompt") in labels_calls
    assert (
        call(provider="google", model="gemini-2.5-flash", token_type="completion") in labels_calls
    )
    inc_calls = mock_metrics.tokens_used_total.labels().inc.call_args_list
    assert call(10) in inc_calls
    assert call(5) in inc_calls


# ---------------------------------------------------------------------------
# generate_stream helpers
# ---------------------------------------------------------------------------


def _make_gemini_chunk(text: str | None) -> MagicMock:
    chunk = MagicMock()
    chunk.text = text
    return chunk


async def _fake_gemini_stream(*chunks):
    for c in chunks:
        yield c


# ---------------------------------------------------------------------------
# generate_stream — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_stream_yields_text_chunks(
    client: GeminiClient, llm_config: LLMConfig
) -> None:
    stream = _fake_gemini_stream(_make_gemini_chunk("Hello "), _make_gemini_chunk("world!"))

    with patch.object(
        client._client.aio.models,
        "generate_content_stream",
        new=AsyncMock(return_value=stream),
    ):
        collected = [
            t
            async for t in client.generate_stream(
                "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
            )
        ]

    assert collected == ["Hello ", "world!"]


@pytest.mark.asyncio
async def test_generate_stream_skips_none_and_empty_chunks(
    client: GeminiClient, llm_config: LLMConfig
) -> None:
    stream = _fake_gemini_stream(
        _make_gemini_chunk("A"),
        _make_gemini_chunk(None),
        _make_gemini_chunk(""),
        _make_gemini_chunk("B"),
    )

    with patch.object(
        client._client.aio.models,
        "generate_content_stream",
        new=AsyncMock(return_value=stream),
    ):
        collected = [
            t
            async for t in client.generate_stream(
                "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
            )
        ]

    assert collected == ["A", "B"]


# ---------------------------------------------------------------------------
# generate_stream — error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_stream_401_raises_llm_auth_error(
    client: GeminiClient, llm_config: LLMConfig
) -> None:
    async def _error_stream():
        raise _client_error(401)
        yield  # make it an async generator

    with patch.object(
        client._client.aio.models,
        "generate_content_stream",
        new=AsyncMock(return_value=_error_stream()),
    ):
        with pytest.raises(LLMAuthError):
            async for _ in client.generate_stream(
                "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
            ):
                pass


@pytest.mark.asyncio
async def test_generate_stream_429_raises_llm_rate_limit_error(
    client: GeminiClient, llm_config: LLMConfig
) -> None:
    async def _error_stream():
        raise _client_error(429)
        yield

    with patch.object(
        client._client.aio.models,
        "generate_content_stream",
        new=AsyncMock(return_value=_error_stream()),
    ):
        with pytest.raises(LLMRateLimitError):
            async for _ in client.generate_stream(
                "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
            ):
                pass


# ---------------------------------------------------------------------------
# generate_stream — metrics emitted after completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_stream_records_metrics_on_completion(
    client: GeminiClient, llm_config: LLMConfig
) -> None:
    stream = _fake_gemini_stream(_make_gemini_chunk("ok"))
    mock_metrics = MagicMock()

    with patch("taskorbit.integrations.llm.gemini_client.get_metrics", return_value=mock_metrics):
        with patch.object(
            client._client.aio.models,
            "generate_content_stream",
            new=AsyncMock(return_value=stream),
        ):
            _ = [
                t
                async for t in client.generate_stream(
                    "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
                )
            ]

    mock_metrics.llm_requests_total.labels.assert_called_with(
        provider="google", model="gemini-2.5-flash", status="success"
    )


@pytest.mark.asyncio
async def test_generate_records_zero_tokens_when_usage_metadata_is_none(
    client: GeminiClient, llm_config: LLMConfig
) -> None:
    fake_response = MagicMock(spec=["text"])  # no usage_metadata attribute
    fake_response.text = "ok"
    mock_metrics = MagicMock()

    with patch("taskorbit.integrations.llm.gemini_client.get_metrics", return_value=mock_metrics):
        with patch.object(
            client._client.aio.models, "generate_content", new=AsyncMock(return_value=fake_response)
        ):
            result = await client.generate(
                "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
            )

    assert result == "ok"
    labels_calls = mock_metrics.tokens_used_total.labels.call_args_list
    assert call(provider="google", model="gemini-2.5-flash", token_type="prompt") in labels_calls
    assert (
        call(provider="google", model="gemini-2.5-flash", token_type="completion") in labels_calls
    )
    inc_calls = mock_metrics.tokens_used_total.labels().inc.call_args_list
    assert call(0) in inc_calls
    assert len([c for c in inc_calls if c == call(0)]) == 2
