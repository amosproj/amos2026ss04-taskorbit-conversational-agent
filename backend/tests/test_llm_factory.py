# TODO: happy-path tests for get_llm_client (returning a working OpenAIClient
# or GeminiClient) require the concrete client modules. Those land with the
# second half of this ticket; add corresponding tests there.

import pytest

from taskorbit.config import Settings
from taskorbit.integrations.llm.errors import LLMConfigError
from taskorbit.integrations.llm.factory import get_llm_client
from taskorbit.types import LLMConfig, LLMProvider


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


def test_unimplemented_openai_client_raises_config_error():
    llm_config = LLMConfig(provider=LLMProvider.OPENAI)
    settings = Settings(openai_api_key="sk-something", google_api_key="")
    with pytest.raises(LLMConfigError, match="not yet implemented"):
        get_llm_client(llm_config, settings=settings)


def test_unimplemented_google_client_raises_config_error():
    llm_config = LLMConfig(provider=LLMProvider.GOOGLE)
    settings = Settings(openai_api_key="", google_api_key="AIza-something")
    with pytest.raises(LLMConfigError, match="not yet implemented"):
        get_llm_client(llm_config, settings=settings)
