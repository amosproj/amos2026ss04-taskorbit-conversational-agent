"""LLM client factory.

Routes per-task to the right concrete client based on AgentConfig.llm.provider.
Env vars in Settings provide API keys and default models only — the provider
choice itself comes from the per-task LLMConfig passed by the caller.
"""

from __future__ import annotations

from taskorbit.config import Settings, get_settings
from taskorbit.types import LLMConfig, LLMProvider

from .base import LLMClient
from .errors import LLMConfigError


def get_llm_client(
    llm_config: LLMConfig,
    settings: Settings | None = None,
) -> LLMClient:
    """Return a concrete LLMClient for the provider named in *llm_config*.

    Parameters
    ----------
    llm_config:
        Per-task LLM configuration, typically from AgentConfig.llm.
    settings:
        Application settings. When *None*, fetched via get_settings().

    Returns
    -------
    LLMClient
        A concrete client whose ``generate`` method is ready to call.

    Raises
    ------
    LLMConfigError
        If the required API key for the selected provider is absent from
        Settings, or if the concrete client module has not been implemented
        yet (ImportError on the lazy import), or if the provider value is
        not a known LLMProvider variant.
    """
    if settings is None:
        settings = get_settings()

    if llm_config.provider == LLMProvider.OPENAI:
        if not settings.openai_api_key:
            raise LLMConfigError("OPENAI_API_KEY is not set; cannot instantiate OpenAIClient")
        try:
            from .openai_client import OpenAIClient  # type: ignore[import]
        except ImportError as exc:
            raise LLMConfigError("OpenAIClient is not yet implemented") from exc
        return OpenAIClient(llm_config=llm_config, settings=settings)

    if llm_config.provider == LLMProvider.GOOGLE:
        if not settings.google_api_key:
            raise LLMConfigError("GOOGLE_API_KEY is not set; cannot instantiate GeminiClient")
        try:
            from .gemini_client import GeminiClient  # type: ignore[import]
        except ImportError as exc:
            raise LLMConfigError("GeminiClient is not yet implemented") from exc
        return GeminiClient(llm_config=llm_config, settings=settings)

    raise LLMConfigError(f"Unexpected LLM provider: {llm_config.provider!r}; no client registered")
