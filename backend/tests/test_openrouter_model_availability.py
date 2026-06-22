"""Integration test: verify all OpenRouter models in the curated list are free and reachable.

Run with:
    OPENROUTER_API_KEY=sk-or-... pytest tests/test_openrouter_model_availability.py -v

Skipped automatically when OPENROUTER_API_KEY is not set so CI stays green.
Each model gets a minimal single-token request — cheap and fast, just enough
to confirm the model accepts free-tier calls without a 404.
"""

from __future__ import annotations

import httpx
import pytest

from taskorbit.config import get_settings

# ---------------------------------------------------------------------------
# Models to validate — keep in sync with frontend/src/lib/pipelineOptions.ts
# ---------------------------------------------------------------------------

OPENROUTER_FREE_MODELS = [
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_MINIMAL_MESSAGES = [{"role": "user", "content": "Reply with one word: hello"}]


@pytest.fixture(scope="module")
def api_key() -> str:
    key = get_settings().openrouter_api_key
    if not key:
        pytest.skip("OPENROUTER_API_KEY not set — skipping OpenRouter availability checks")
    return key


@pytest.mark.parametrize("model", OPENROUTER_FREE_MODELS)
def test_model_is_free_and_reachable(model: str, api_key: str) -> None:
    """Send a minimal request to each model and assert it returns a 200."""
    response = httpx.post(
        f"{_OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://taskorbit.app",
            "X-Title": "TaskOrbit",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": _MINIMAL_MESSAGES,
            "max_tokens": 5,
        },
        timeout=30.0,
    )

    if response.status_code == 404:
        body = response.json()
        message = body.get("error", {}).get("message", "")
        pytest.fail(
            f"Model '{model}' is not available for free.\n"
            f"OpenRouter says: {message}\n"
            f"Remove or replace this slug in frontend/src/lib/pipelineOptions.ts"
        )

    # 429 means the model exists and is free but is temporarily rate-limited — treat as pass.
    assert response.status_code in (
        200,
        429,
    ), f"Model '{model}' returned unexpected status {response.status_code}:\n{response.text}"
