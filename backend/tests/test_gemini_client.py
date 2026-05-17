"""Unit tests for GeminiClient.

Mocks the google-genai async client so tests never make real network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
    llm_config = LLMConfig(provider=LLMProvider.GOOGLE, model="gemini-2.0-flash")
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
    return LLMConfig(provider=LLMProvider.GOOGLE, model="gemini-2.0-flash")


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
    assert call_kwargs["model"] == "gemini-2.0-flash"
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
