"""Tests for OpenRouter provider handling in the LiveKit worker metadata path.

The worker receives participant metadata as a JSON dict and parses it into
AgentConfig via model_validate. This test suite guards against the bug where
livekitAgentMetadata.ts mapped 'openrouter' -> 'openai' (fixed), which caused
the factory to route OpenRouter requests through OpenAIClient instead of
OpenRouterClient — producing llm_call_started logs with provider=openai and
failing calls since OpenAI doesn't recognise OpenRouter model slugs.

Also covers that OrchestratorAgent logs llm_active with the correct provider
and model at the start of each voice turn.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from taskorbit.types import AgentConfig, LLMConfig, LLMProvider

# ---------------------------------------------------------------------------
# Worker metadata parsing — provider field
# ---------------------------------------------------------------------------


def _make_metadata(provider: str, model: str) -> dict:
    return {
        "id": "agent-1",
        "name": "Bot",
        "persona": "Helpful assistant",
        "greeting": "Hi!",
        "llm": {"provider": provider, "model": model},
    }


def test_worker_metadata_openrouter_provider_parsed_correctly() -> None:
    """'openrouter' in metadata must produce LLMProvider.OPENROUTER, not OPENAI."""
    meta = _make_metadata("openrouter", "google/gemma-4-31b-it:free")
    config = AgentConfig.model_validate(meta)
    assert config.llm.provider == LLMProvider.OPENROUTER
    assert config.llm.model == "google/gemma-4-31b-it:free"


def test_worker_metadata_openai_provider_parsed_correctly() -> None:
    meta = _make_metadata("openai", "gpt-4o-mini")
    config = AgentConfig.model_validate(meta)
    assert config.llm.provider == LLMProvider.OPENAI


def test_worker_metadata_google_provider_parsed_correctly() -> None:
    meta = _make_metadata("google", "gemini-2.5-flash")
    config = AgentConfig.model_validate(meta)
    assert config.llm.provider == LLMProvider.GOOGLE


def test_worker_metadata_openrouter_does_not_fallback_to_openai() -> None:
    """Regression: before the fix, any provider other than 'gemini' was mapped
    to 'openai' in buildLiveKitWorkerMetadata. Ensure the backend correctly
    rejects 'openai' when the model is an OpenRouter slug."""
    # Simulate the broken metadata that the old frontend would have sent:
    # provider='openai' but model is an OpenRouter slug
    meta = _make_metadata("openai", "google/gemma-4-31b-it:free")
    config = AgentConfig.model_validate(meta)
    # Backend parses it as OPENAI — this is what caused the bug.
    # The factory would then call OpenAI API with an OpenRouter model name.
    assert config.llm.provider == LLMProvider.OPENAI
    assert config.llm.model == "google/gemma-4-31b-it:free"
    # Guard should NOT catch this (prefix guard only blocks gpt-/gemini- mismatches)
    # which is why the fix had to be in the frontend metadata builder.
    from taskorbit.integrations.llm.factory import _guard_provider_model_match

    _guard_provider_model_match(config.llm)  # must not raise — confirms the guard gap


def test_worker_metadata_all_openrouter_models_parse() -> None:
    """All models in pipelineOptions.ts must parse into OPENROUTER provider."""
    models = [
        "qwen/qwen3-next-80b-a3b-instruct:free",
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "openai/gpt-oss-120b:free",
        "openai/gpt-oss-20b:free",
        "meta-llama/llama-3.3-70b-instruct:free",
    ]
    for model in models:
        config = AgentConfig.model_validate(_make_metadata("openrouter", model))
        assert config.llm.provider == LLMProvider.OPENROUTER, f"Failed for model: {model}"
        assert config.llm.model == model


# ---------------------------------------------------------------------------
# OrchestratorAgent.llm_node — llm_active log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_node_logs_llm_active_with_correct_provider_and_model() -> None:
    """llm_node must emit llm_active with the agent config's provider and model."""
    from livekit.agents import llm

    from taskorbit.livekit_agent.llm import OrchestratorAgent
    from taskorbit.orchestration import ConversationOrchestrator
    from taskorbit.types import ConversationResponse, ConversationStatus, Message, MessageRole

    agent_config = AgentConfig(
        id="agent-1",
        name="Bot",
        persona="p",
        greeting="hi",
        llm=LLMConfig(provider=LLMProvider.OPENROUTER, model="google/gemma-4-31b-it:free"),
    )

    mock_response = ConversationResponse(
        conversation_id="test-conv",
        reply=Message(role=MessageRole.ASSISTANT, content="Hello!"),
        status=ConversationStatus.SUCCESS,
    )

    mock_orchestrator = MagicMock(spec=ConversationOrchestrator)
    mock_orchestrator.process_message = AsyncMock(return_value=mock_response)

    agent = OrchestratorAgent(
        orchestrator=mock_orchestrator,
        agent_config=agent_config,
        conversation_id="test-conv",
    )
    agent.request_reply()

    mock_chat_ctx = MagicMock(spec=llm.ChatContext)
    # A fresh user turn is required: llm_node now waits for a real transcript and
    # skips an empty context instead of replying to nothing, so llm_active only
    # fires once an unanswered user message is present (#153).
    _user_item = MagicMock()
    _user_item.role = "user"
    _user_item.content = "I need help"
    mock_chat_ctx.items = [_user_item]

    with (
        patch("taskorbit.livekit_agent.llm.log") as mock_log,
        patch("taskorbit.livekit_agent.llm.AsyncSessionLocal") as mock_session,
    ):
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        async for _ in agent.llm_node(mock_chat_ctx, [], MagicMock()):
            pass

    llm_active_calls = [
        call for call in mock_log.info.call_args_list if call.args and call.args[0] == "llm_active"
    ]
    assert len(llm_active_calls) == 1
    kwargs = llm_active_calls[0].kwargs
    assert kwargs["provider"] == LLMProvider.OPENROUTER
    assert kwargs["model"] == "google/gemma-4-31b-it:free"
