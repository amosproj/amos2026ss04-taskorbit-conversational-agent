"""Shared pytest fixtures for the TaskOrbit backend test suite."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _no_real_llm_json_calls():
    """Keep orchestrator JSON calls (slot extraction, intent routing) off the network.

    _call_llm_json previously hit the real provider during slot extraction and
    the resulting errors (e.g. OpenAI 429 insufficient_quota) were silently
    swallowed — the exact masking #197 removes. Now that provider errors surface,
    an unmocked call would fail the turn, so default to an empty JSON object
    (= no slots found). Tests that need provider failures or custom JSON
    re-patch the method inside their own scope.
    """
    from taskorbit.orchestration import ConversationOrchestrator

    with patch.object(
        ConversationOrchestrator, "_call_llm_json", new_callable=AsyncMock, return_value="{}"
    ):
        yield


@pytest.fixture
def mock_good_intent():
    """Patch IntentRouter.detect to return a valid intent result.

    Without this, tests that mock _call_llm (or get_llm_client) cause
    the intent router to receive non-JSON and log intent_router_parse_error,
    returning requires_clarification=True which short-circuits the orchestrator
    before the test's assertions are reached.

    Uses book_service_appointment so tests that check selected_intent still pass.
    """
    from taskorbit.intent import _KNOWN_INTENTS

    good = replace(
        _KNOWN_INTENTS["book_service_appointment"],
        confidence=0.9,
        requires_clarification=False,
    )
    with patch(
        "taskorbit.intent.IntentRouter.detect",
        new_callable=AsyncMock,
        return_value=good,
    ):
        yield good
