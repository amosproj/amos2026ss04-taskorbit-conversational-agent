import pytest

from taskorbit.config import Settings
from taskorbit.integrations.llm.errors import LLMConfigError
from taskorbit.integrations.llm.factory import _guard_provider_model_match, get_llm_client
from taskorbit.integrations.llm.gemini_client import GeminiClient
from taskorbit.integrations.llm.openai_client import OpenAIClient
from taskorbit.types import LLMConfig, LLMProvider

# ---------------------------------------------------------------------------
# Negative paths — missing API keys
# ---------------------------------------------------------------------------


def test_missing_openai_key_raises_config_error():
    llm_config = LLMConfig(provider=LLMProvider.OPENAI)
    settings = Settings(openai_api_key="", google_api_key="anything")
    with pytest.raises(LLMConfigError, match="OPENAI_API_KEY"):
        get_llm_client(llm_config, settings=settings)


def test_missing_google_key_raises_config_error():
    # Explicit Gemini model so the provider/model guard passes and the missing
    # key is what triggers the error (LLMConfig defaults model to gpt-4o-mini).
    llm_config = LLMConfig(provider=LLMProvider.GOOGLE, model="gemini-2.5-flash")
    settings = Settings(openai_api_key="anything", google_api_key="")
    with pytest.raises(LLMConfigError, match="GOOGLE_API_KEY"):
        get_llm_client(llm_config, settings=settings)


# ---------------------------------------------------------------------------
# Happy paths — factory returns concrete client when key is present
# ---------------------------------------------------------------------------


def test_openai_provider_returns_openai_client():
    llm_config = LLMConfig(provider=LLMProvider.OPENAI, model="gpt-4o-mini")
    settings = Settings(openai_api_key="sk-test-key", google_api_key="")
    client = get_llm_client(llm_config, settings=settings)
    assert isinstance(client, OpenAIClient)


def test_google_provider_returns_gemini_client():
    llm_config = LLMConfig(provider=LLMProvider.GOOGLE, model="gemini-2.5-flash")
    settings = Settings(openai_api_key="", google_api_key="AIza-test-key")
    client = get_llm_client(llm_config, settings=settings)
    assert isinstance(client, GeminiClient)


# ---------------------------------------------------------------------------
# Provider/model mismatch guard (ticket #99)
# ---------------------------------------------------------------------------


def test_google_provider_with_openai_model_raises_config_error():
    llm_config = LLMConfig(provider=LLMProvider.GOOGLE, model="gpt-4o-mini")
    with pytest.raises(LLMConfigError, match="gpt-4o-mini"):
        _guard_provider_model_match(llm_config)


def test_openai_provider_with_gemini_model_raises_config_error():
    llm_config = LLMConfig(provider=LLMProvider.OPENAI, model="gemini-2.5-flash")
    with pytest.raises(LLMConfigError, match="gemini-2.5-flash"):
        _guard_provider_model_match(llm_config)


def test_openai_provider_with_openai_model_passes():
    llm_config = LLMConfig(provider=LLMProvider.OPENAI, model="gpt-4o-mini")
    _guard_provider_model_match(llm_config)


def test_google_provider_with_gemini_model_passes():
    llm_config = LLMConfig(provider=LLMProvider.GOOGLE, model="gemini-2.5-flash")
    _guard_provider_model_match(llm_config)


# ---------------------------------------------------------------------------
# OpenRouter provider (open-source models via OpenRouter API)
# ---------------------------------------------------------------------------


def test_missing_openrouter_key_raises_config_error():
    llm_config = LLMConfig(provider=LLMProvider.OPENROUTER, model="google/gemma-4-31b-it:free")
    settings = Settings(openrouter_api_key="")
    with pytest.raises(LLMConfigError, match="OPENROUTER_API_KEY"):
        get_llm_client(llm_config, settings=settings)


def test_openrouter_provider_returns_openrouter_client():
    from unittest.mock import patch

    from taskorbit.integrations.llm.openrouter_client import OpenRouterClient

    llm_config = LLMConfig(provider=LLMProvider.OPENROUTER, model="google/gemma-4-31b-it:free")
    settings = Settings(openrouter_api_key="sk-or-test")
    with patch("taskorbit.integrations.llm.openrouter_client.OpenRouter"):
        client = get_llm_client(llm_config, settings=settings)
    assert isinstance(client, OpenRouterClient)


def test_openrouter_namespaced_model_bypasses_prefix_guard():
    """Free-form org/model:free slugs must not trigger the gpt-/gemini- prefix guard."""
    for model in [
        "qwen/qwen3-next-80b-a3b-instruct:free",
        "google/gemma-4-31b-it:free",
        "openai/gpt-oss-120b:free",
        "meta-llama/llama-3.3-70b-instruct:free",
    ]:
        _guard_provider_model_match(LLMConfig(provider=LLMProvider.OPENROUTER, model=model))
