"""Integration tests for OllamaClient against a live Ollama endpoint.

These tests are SKIPPED in normal CI — they only run when OLLAMA_BASE_URL
is set to a real endpoint (local Ollama or the Cloud Run service URL).

Run manually for Phase 6 acceptance validation:
    # Against local Ollama (docker run -p 11434:11434 ollama/ollama):
    OLLAMA_BASE_URL=http://localhost:11434 poetry run pytest tests/test_ollama_integration.py -v

    # Against Cloud Run (requires gcloud auth):
    OLLAMA_BASE_URL=$(gcloud run services describe taskorbit-ollama-inference \
      --region=europe-west3 --format="value(status.url)") \
    poetry run pytest tests/test_ollama_integration.py -v

All tests require the models listed in REQUIRED_MODELS to be pulled and
available at the endpoint. Pre-pull with: ollama pull gemma4:26b && ollama pull qwen3.6:27b
"""

from __future__ import annotations

import os

import pytest

from taskorbit.config import get_settings
from taskorbit.integrations.llm.factory import get_llm_client
from taskorbit.integrations.llm.ollama_client import OllamaClient
from taskorbit.types import LLMConfig, LLMProvider, Message, MessageRole

# ── Skip guard ────────────────────────────────────────────────────────────────

_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "")
_SKIP = not _BASE_URL

pytestmark = pytest.mark.skipif(
    _SKIP,
    reason="OLLAMA_BASE_URL not set — skipping Ollama integration tests",
)

# Models that must be available at the endpoint for validation to pass.
# These match the GPU inference module's gpu_inference_models defaults.
REQUIRED_MODELS = ["gemma4:26b", "qwen3.6:27b"]
PRIMARY_MODEL = "gemma4:26b"
SWAP_MODEL = "qwen3.6:27b"

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def settings(monkeypatch_module):
    monkeypatch_module.setenv("OLLAMA_BASE_URL", _BASE_URL)
    monkeypatch_module.setenv("OLLAMA_MODEL", PRIMARY_MODEL)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch so settings are set once for all tests."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


def _make_llm_config(model: str = PRIMARY_MODEL) -> LLMConfig:
    return LLMConfig(provider=LLMProvider.OLLAMA, model=model)


def _make_messages(text: str) -> list[Message]:
    return [Message(role=MessageRole.USER, content=text)]


# ── Check 1: Service reachability ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ollama_endpoint_is_reachable() -> None:
    """GET /api/tags must return 200 — confirms service is up and models dir is mounted."""
    import httpx

    is_https = _BASE_URL.startswith("https://")
    headers = {}
    if is_https:
        from taskorbit.integrations.llm.ollama_client import _get_identity_token

        token = await _get_identity_token(_BASE_URL)
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{_BASE_URL}/api/tags", headers=headers)

    assert resp.status_code == 200, f"/api/tags returned {resp.status_code}: {resp.text[:200]}"


# ── Check 2: Required models are loaded ───────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("model", REQUIRED_MODELS)
async def test_required_model_is_available(model: str) -> None:
    """Each entry in REQUIRED_MODELS must appear in /api/tags response."""
    import httpx

    is_https = _BASE_URL.startswith("https://")
    headers = {}
    if is_https:
        from taskorbit.integrations.llm.ollama_client import _get_identity_token

        token = await _get_identity_token(_BASE_URL)
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{_BASE_URL}/api/tags", headers=headers)

    assert resp.status_code == 200
    loaded = [m["name"] for m in resp.json().get("models", [])]
    assert model in loaded, (
        f"Model {model!r} not found at {_BASE_URL}. "
        f"Loaded models: {loaded}. "
        f"Pull it with: ollama pull {model}"
    )


# ── Check 3: Completion with primary model ────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_returns_text_from_primary_model(monkeypatch_module) -> None:
    """A real generate() call to PRIMARY_MODEL must return non-empty assistant text."""
    monkeypatch_module.setenv("OLLAMA_BASE_URL", _BASE_URL)
    monkeypatch_module.setenv("OLLAMA_MODEL", PRIMARY_MODEL)
    get_settings.cache_clear()
    settings = get_settings()

    llm_config = _make_llm_config(PRIMARY_MODEL)
    client = OllamaClient(llm_config=llm_config, settings=settings)

    result = await client.generate(
        system_prompt="You are a helpful assistant. Reply concisely.",
        messages=_make_messages("Say exactly: VALIDATION_OK"),
        llm_config=llm_config,
    )

    assert isinstance(result, str)
    assert len(result) > 0, "generate() returned an empty string"
    get_settings.cache_clear()


# ── Check 4: Completion with swap model ──────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_returns_text_from_swap_model(monkeypatch_module) -> None:
    """SWAP_MODEL must also respond — validates both models are correctly loaded."""
    monkeypatch_module.setenv("OLLAMA_BASE_URL", _BASE_URL)
    monkeypatch_module.setenv("OLLAMA_MODEL", SWAP_MODEL)
    get_settings.cache_clear()
    settings = get_settings()

    llm_config = _make_llm_config(SWAP_MODEL)
    client = OllamaClient(llm_config=llm_config, settings=settings)

    result = await client.generate(
        system_prompt="You are a helpful assistant. Reply concisely.",
        messages=_make_messages("Say exactly: VALIDATION_OK"),
        llm_config=llm_config,
    )

    assert isinstance(result, str)
    assert len(result) > 0, "generate() returned an empty string for swap model"
    get_settings.cache_clear()


# ── Check 5: Streaming with primary model ─────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_stream_yields_tokens(monkeypatch_module) -> None:
    """Streaming must yield at least one non-empty token chunk."""
    monkeypatch_module.setenv("OLLAMA_BASE_URL", _BASE_URL)
    monkeypatch_module.setenv("OLLAMA_MODEL", PRIMARY_MODEL)
    get_settings.cache_clear()
    settings = get_settings()

    llm_config = _make_llm_config(PRIMARY_MODEL)
    client = OllamaClient(llm_config=llm_config, settings=settings)

    tokens: list[str] = []
    async for token in client.generate_stream(
        system_prompt="You are helpful.",
        messages=_make_messages("Count to 3."),
        llm_config=llm_config,
    ):
        tokens.append(token)

    assert len(tokens) > 0, "generate_stream() yielded no tokens"
    full_text = "".join(tokens)
    assert len(full_text) > 0
    get_settings.cache_clear()


# ── Check 6: Factory returns OllamaClient ─────────────────────────────────────


def test_factory_returns_ollama_client_for_live_url(monkeypatch_module) -> None:
    """get_llm_client() must return OllamaClient when OLLAMA_BASE_URL is set."""
    monkeypatch_module.setenv("OLLAMA_BASE_URL", _BASE_URL)
    monkeypatch_module.setenv("OLLAMA_MODEL", PRIMARY_MODEL)
    get_settings.cache_clear()
    settings = get_settings()

    llm_config = _make_llm_config()
    client = get_llm_client(llm_config, settings=settings)

    assert isinstance(client, OllamaClient)
    assert PRIMARY_MODEL in client._llm_config.model
    get_settings.cache_clear()
