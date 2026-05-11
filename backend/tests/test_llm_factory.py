import pytest

from taskorbit.config import Settings
from taskorbit.integrations.llm.errors import LLMConfigError
from taskorbit.integrations.llm.factory import get_llm_client
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
    llm_config = LLMConfig(provider=LLMProvider.GOOGLE)
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
    llm_config = LLMConfig(provider=LLMProvider.GOOGLE, model="gemini-2.0-flash")
    settings = Settings(openai_api_key="", google_api_key="AIza-test-key")
    client = get_llm_client(llm_config, settings=settings)
    assert isinstance(client, GeminiClient)
