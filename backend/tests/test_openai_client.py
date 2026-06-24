"""Unit tests for OpenAIClient.

Mocks the openai AsyncOpenAI client so tests never make real network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import openai
import pytest

from taskorbit.config import Settings
from taskorbit.integrations.llm.errors import (
    LLMAPIError,
    LLMAuthError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from taskorbit.integrations.llm.openai_client import OpenAIClient
from taskorbit.types import LLMConfig, LLMProvider, Message, MessageRole


def _make_client() -> OpenAIClient:
    """Construct a client with fake credentials for testing."""
    settings = Settings(openai_api_key="sk-test-key", google_api_key="")
    llm_config = LLMConfig(provider=LLMProvider.OPENAI, model="gpt-4o-mini")
    return OpenAIClient(llm_config=llm_config, settings=settings)


def _mock_completion_response(content: str | None) -> MagicMock:
    """Build a fake ChatCompletion response with the given assistant content."""
    response = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    response.choices = [choice] if content is not None or content == "" else []
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 5
    return response


@pytest.fixture
def client() -> OpenAIClient:
    return _make_client()


@pytest.fixture
def llm_config() -> LLMConfig:
    return LLMConfig(provider=LLMProvider.OPENAI, model="gpt-4o-mini")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_returns_assistant_text(client: OpenAIClient, llm_config: LLMConfig) -> None:
    fake_response = _mock_completion_response("4")
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=fake_response)
    ) as mock_create:
        result = await client.generate(
            "You are a helpful assistant.",
            [Message(role=MessageRole.USER, content="What is 2+2?")],
            llm_config,
        )

    assert result == "4"
    # Verify the SDK was called with the right model and a wire-format message list
    # that prepends the system prompt and includes the user message.
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"
    assert call_kwargs["messages"][0] == {
        "role": "system",
        "content": "You are a helpful assistant.",
    }
    assert call_kwargs["messages"][1] == {"role": "user", "content": "What is 2+2?"}


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_error_maps_to_llm_auth_error(
    client: OpenAIClient, llm_config: LLMConfig
) -> None:
    auth_exc = openai.AuthenticationError(
        message="Invalid API key", response=MagicMock(status_code=401), body=None
    )
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=auth_exc)
    ):
        with pytest.raises(LLMAuthError):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


@pytest.mark.asyncio
async def test_rate_limit_maps_to_llm_rate_limit_error(
    client: OpenAIClient, llm_config: LLMConfig
) -> None:
    rate_exc = openai.RateLimitError(
        message="Rate limited", response=MagicMock(status_code=429), body=None
    )
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=rate_exc)
    ):
        with pytest.raises(LLMRateLimitError):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


@pytest.mark.asyncio
async def test_timeout_maps_to_llm_timeout_error(
    client: OpenAIClient, llm_config: LLMConfig
) -> None:
    timeout_exc = openai.APITimeoutError(request=MagicMock())
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=timeout_exc)
    ):
        with pytest.raises(LLMTimeoutError):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


@pytest.mark.asyncio
async def test_generic_api_error_maps_to_llm_api_error(
    client: OpenAIClient, llm_config: LLMConfig
) -> None:
    api_exc = openai.APIError(message="Server error", request=MagicMock(), body=None)
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=api_exc)
    ):
        with pytest.raises(LLMAPIError):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


# ---------------------------------------------------------------------------
# Empty response handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_content_raises_llm_api_error(
    client: OpenAIClient, llm_config: LLMConfig
) -> None:
    fake_response = _mock_completion_response("")
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=fake_response)
    ):
        with pytest.raises(LLMAPIError, match="empty"):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


@pytest.mark.asyncio
async def test_no_choices_raises_llm_api_error(client: OpenAIClient, llm_config: LLMConfig) -> None:
    fake_response = MagicMock()
    fake_response.choices = []
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=fake_response)
    ):
        with pytest.raises(LLMAPIError, match="empty"):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)


# ---------------------------------------------------------------------------
# Token usage metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_records_token_metrics(client: OpenAIClient, llm_config: LLMConfig) -> None:
    fake_response = _mock_completion_response("4")  # usage.prompt_tokens=10, completion_tokens=5
    mock_metrics = MagicMock()

    with patch("taskorbit.integrations.llm.openai_client.get_metrics", return_value=mock_metrics):
        with patch.object(
            client._client.chat.completions, "create", new=AsyncMock(return_value=fake_response)
        ):
            await client.generate("sys", [Message(role=MessageRole.USER, content="hi")], llm_config)

    labels_calls = mock_metrics.tokens_used_total.labels.call_args_list
    assert call(provider="openai", model="gpt-4o-mini", token_type="prompt") in labels_calls
    assert call(provider="openai", model="gpt-4o-mini", token_type="completion") in labels_calls
    inc_calls = mock_metrics.tokens_used_total.labels().inc.call_args_list
    assert call(10) in inc_calls
    assert call(5) in inc_calls


# ---------------------------------------------------------------------------
# generate_stream helpers
# ---------------------------------------------------------------------------


class _FakeStream:
    """Minimal async-iterable + close() shim that stands in for openai AsyncStream."""

    def __init__(self, chunks: list) -> None:
        self._chunks = iter(chunks)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration

    async def close(self) -> None:
        self.closed = True


def _make_stream_chunk(delta_content: str | None = None, usage=None) -> MagicMock:
    chunk = MagicMock()
    if delta_content is not None:
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = delta_content
    else:
        chunk.choices = []
    chunk.usage = usage
    return chunk


# ---------------------------------------------------------------------------
# generate_stream — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_stream_yields_text_chunks(
    client: OpenAIClient, llm_config: LLMConfig
) -> None:
    chunks = [_make_stream_chunk("Hello "), _make_stream_chunk("world!")]
    fake_stream = _FakeStream(chunks)

    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=fake_stream)
    ):
        collected = [
            t
            async for t in client.generate_stream(
                "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
            )
        ]

    assert collected == ["Hello ", "world!"]
    assert fake_stream.closed


@pytest.mark.asyncio
async def test_generate_stream_assembles_to_full_text(
    client: OpenAIClient, llm_config: LLMConfig
) -> None:
    chunks = [_make_stream_chunk("A"), _make_stream_chunk("B"), _make_stream_chunk("C")]
    fake_stream = _FakeStream(chunks)

    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=fake_stream)
    ):
        result = "".join(
            [
                t
                async for t in client.generate_stream(
                    "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
                )
            ]
        )

    assert result == "ABC"


@pytest.mark.asyncio
async def test_generate_stream_skips_empty_delta(
    client: OpenAIClient, llm_config: LLMConfig
) -> None:
    chunks = [
        _make_stream_chunk("Hi"),
        _make_stream_chunk(None),  # no-content delta — must be filtered
        _make_stream_chunk(" there"),
    ]
    fake_stream = _FakeStream(chunks)

    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=fake_stream)
    ):
        collected = [
            t
            async for t in client.generate_stream(
                "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
            )
        ]

    assert collected == ["Hi", " there"]


# ---------------------------------------------------------------------------
# generate_stream — error mapping on stream initiation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_stream_auth_error_raises_llm_auth_error(
    client: OpenAIClient, llm_config: LLMConfig
) -> None:
    auth_exc = openai.AuthenticationError(
        message="Invalid key", response=MagicMock(status_code=401), body=None
    )
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=auth_exc)
    ):
        with pytest.raises(LLMAuthError):
            async for _ in client.generate_stream(
                "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
            ):
                pass


@pytest.mark.asyncio
async def test_generate_stream_rate_limit_raises_llm_rate_limit_error(
    client: OpenAIClient, llm_config: LLMConfig
) -> None:
    rate_exc = openai.RateLimitError(
        message="Rate limited", response=MagicMock(status_code=429), body=None
    )
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=rate_exc)
    ):
        with pytest.raises(LLMRateLimitError):
            async for _ in client.generate_stream(
                "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
            ):
                pass


@pytest.mark.asyncio
async def test_generate_stream_timeout_raises_llm_timeout_error(
    client: OpenAIClient, llm_config: LLMConfig
) -> None:
    with patch.object(
        client._client.chat.completions,
        "create",
        new=AsyncMock(side_effect=openai.APITimeoutError(request=MagicMock())),
    ):
        with pytest.raises(LLMTimeoutError):
            async for _ in client.generate_stream(
                "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
            ):
                pass


# ---------------------------------------------------------------------------
# generate_stream — metrics emitted after completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_stream_records_metrics_on_completion(
    client: OpenAIClient, llm_config: LLMConfig
) -> None:
    usage = MagicMock(prompt_tokens=8, completion_tokens=4)
    chunks = [_make_stream_chunk("ok"), _make_stream_chunk(None, usage=usage)]
    fake_stream = _FakeStream(chunks)
    mock_metrics = MagicMock()

    with patch("taskorbit.integrations.llm.openai_client.get_metrics", return_value=mock_metrics):
        with patch.object(
            client._client.chat.completions, "create", new=AsyncMock(return_value=fake_stream)
        ):
            _ = [
                t
                async for t in client.generate_stream(
                    "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
                )
            ]

    mock_metrics.llm_requests_total.labels.assert_called_with(
        provider="openai", model="gpt-4o-mini", status="success"
    )


@pytest.mark.asyncio
async def test_generate_records_zero_tokens_when_usage_is_none(
    client: OpenAIClient, llm_config: LLMConfig
) -> None:
    fake_response = MagicMock()
    choice = MagicMock()
    choice.message.content = "ok"
    fake_response.choices = [choice]
    fake_response.usage = None
    mock_metrics = MagicMock()

    with patch("taskorbit.integrations.llm.openai_client.get_metrics", return_value=mock_metrics):
        with patch.object(
            client._client.chat.completions, "create", new=AsyncMock(return_value=fake_response)
        ):
            result = await client.generate(
                "sys", [Message(role=MessageRole.USER, content="hi")], llm_config
            )

    assert result == "ok"
    labels_calls = mock_metrics.tokens_used_total.labels.call_args_list
    assert call(provider="openai", model="gpt-4o-mini", token_type="prompt") in labels_calls
    assert call(provider="openai", model="gpt-4o-mini", token_type="completion") in labels_calls
    inc_calls = mock_metrics.tokens_used_total.labels().inc.call_args_list
    assert call(0) in inc_calls
    assert len([c for c in inc_calls if c == call(0)]) == 2
