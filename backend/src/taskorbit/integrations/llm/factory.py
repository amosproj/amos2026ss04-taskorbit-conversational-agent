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

# A mismatched provider/model pair (ticket #99) used to reach the concrete
# client untouched — a Gemini client handed an OpenAI model returns 404 mid
# voice turn. Fail fast here with a clear error instead. Prefix-based on
# purpose: it only rejects names that unambiguously belong elsewhere and
# leaves anything it doesn't recognise to the provider to validate.
# OPENROUTER is excluded: model names are free-form namespaced strings
# (e.g. "qwen/qwen-2.5-7b-instruct:free") that don't share any prefix with
# the cloud providers, so no cross-provider confusion is possible.
_PROVIDER_MODEL_PREFIXES = {
    LLMProvider.OPENAI: "gpt-",
    LLMProvider.GOOGLE: "gemini-",
}


def _guard_provider_model_match(llm_config: LLMConfig) -> None:
    model = llm_config.model.lower()
    for provider, prefix in _PROVIDER_MODEL_PREFIXES.items():
        if model.startswith(prefix) and llm_config.provider != provider:
            raise LLMConfigError(
                f"Model {llm_config.model!r} belongs to provider "
                f"{provider.value!r}, not the selected provider "
                f"{llm_config.provider.value!r}"
            )


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

    _guard_provider_model_match(llm_config)

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

    if llm_config.provider == LLMProvider.OPENROUTER:
        if not settings.openrouter_api_key:
            raise LLMConfigError(
                "OPENROUTER_API_KEY is not set; cannot instantiate OpenRouterClient. "
                "Get a free key at https://openrouter.ai/keys"
            )
        try:
            from .openrouter_client import OpenRouterClient  # type: ignore[import]
        except ImportError as exc:
            raise LLMConfigError("OpenRouterClient is not yet implemented") from exc
        return OpenRouterClient(llm_config=llm_config, settings=settings)

    if llm_config.provider == LLMProvider.OLLAMA:
        if not settings.ollama_base_url:
            raise LLMConfigError(
                "OLLAMA_BASE_URL is not set; cannot instantiate OllamaClient. "
                "Set it to the Ollama Cloud Run service URL or http://localhost:11434 for local dev."
            )
        try:
            from .ollama_client import OllamaClient  # type: ignore[import]
        except ImportError as exc:
            raise LLMConfigError("OllamaClient is not yet implemented") from exc
        return OllamaClient(llm_config=llm_config, settings=settings)

    raise LLMConfigError(f"Unexpected LLM provider: {llm_config.provider!r}; no client registered")
