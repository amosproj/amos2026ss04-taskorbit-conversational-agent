"""Integration tests for ConversationOrchestrator._call_llm.

Verifies that _call_llm correctly wires together the factory, the
same-language prompt helper, and the concrete client's generate method.
SDK calls themselves are out of scope here — that's covered by
test_openai_client.py and test_gemini_client.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.config import Settings
from taskorbit.integrations.llm.errors import LLMAPIError
from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import LLMConfig, LLMProvider, Message, MessageRole


def _make_orchestrator() -> ConversationOrchestrator:
    """Construct an orchestrator with fake credentials for both providers."""
    settings = Settings(openai_api_key="sk-test-key", google_api_key="AIza-test-key")
    return ConversationOrchestrator(settings=settings)


def _make_messages() -> list[Message]:
    return [Message(role=MessageRole.USER, content="What is 2+2?")]


@pytest.fixture
def orchestrator() -> ConversationOrchestrator:
    return _make_orchestrator()


# ---------------------------------------------------------------------------
# Factory + helper + client.generate are all wired together
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_llm_invokes_factory_with_llm_config(
    orchestrator: ConversationOrchestrator,
) -> None:
    """Factory must be called with the same LLMConfig _call_llm received."""
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="ok")
    llm_config = LLMConfig(provider=LLMProvider.OPENAI, model="gpt-4o-mini")

    with patch(
        "taskorbit.integrations.llm.factory.get_llm_client", return_value=mock_client
    ) as mock_factory:
        await orchestrator._call_llm("You are helpful.", _make_messages(), llm_config)

    # Factory invoked once, with the exact llm_config and the orchestrator's settings.
    mock_factory.assert_called_once()
    args, kwargs = mock_factory.call_args
    assert args[0] is llm_config
    assert kwargs["settings"] is orchestrator._settings


@pytest.mark.asyncio
async def test_call_llm_appends_same_language_instruction(
    orchestrator: ConversationOrchestrator,
) -> None:
    """The system prompt passed to the client must include the multilingual directive."""
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="ok")
    llm_config = LLMConfig(provider=LLMProvider.OPENAI, model="gpt-4o-mini")

    with patch(
        "taskorbit.integrations.llm.factory.get_llm_client", return_value=mock_client
    ):
        await orchestrator._call_llm("You are helpful.", _make_messages(), llm_config)

    # client.generate was called with the augmented prompt.
    augmented_prompt = mock_client.generate.call_args.args[0]
    assert augmented_prompt.startswith("You are helpful.")
    assert "Respond in the same language" in augmented_prompt


@pytest.mark.asyncio
async def test_call_llm_returns_client_response(
    orchestrator: ConversationOrchestrator,
) -> None:
    """Whatever the client's generate returns becomes _call_llm's return value."""
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="4")
    llm_config = LLMConfig(provider=LLMProvider.OPENAI, model="gpt-4o-mini")

    with patch(
        "taskorbit.integrations.llm.factory.get_llm_client", return_value=mock_client
    ):
        result = await orchestrator._call_llm("sys", _make_messages(), llm_config)

    assert result == "4"


@pytest.mark.asyncio
async def test_call_llm_propagates_client_errors(
    orchestrator: ConversationOrchestrator,
) -> None:
    """Errors raised by the client's generate must NOT be swallowed."""
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(side_effect=LLMAPIError("boom"))
    llm_config = LLMConfig(provider=LLMProvider.OPENAI, model="gpt-4o-mini")

    with patch(
        "taskorbit.integrations.llm.factory.get_llm_client", return_value=mock_client
    ):
        with pytest.raises(LLMAPIError, match="boom"):
            await orchestrator._call_llm("sys", _make_messages(), llm_config)
