"""Unit tests for IntentRouter (Task 7 — agent routing foundation, #8)."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from taskorbit.intent import (
    _KNOWN_INTENTS,
    CONFIDENCE_THRESHOLD,
    IntentRouter,
)


@pytest.fixture
def router() -> IntentRouter:
    return IntentRouter()


# ---------------------------------------------------------------------------
# detect() — confidence handling
# ---------------------------------------------------------------------------


async def test_high_confidence_returns_intent_without_clarification(router: IntentRouter) -> None:
    llm_fn = AsyncMock(return_value='{"intent": "book_service_appointment", "confidence": 0.9}')
    result = await router.detect("I want to book a plumber.", [], llm_fn, Mock())
    assert result.name == "book_service_appointment"
    assert result.agent_name == "sales"
    assert result.requires_clarification is False
    assert result.confidence == 0.9


async def test_low_confidence_sets_clarification_flag(router: IntentRouter) -> None:
    llm_fn = AsyncMock(return_value='{"intent": "book_service_appointment", "confidence": 0.4}')
    result = await router.detect("uhh, maybe?", [], llm_fn, Mock())
    assert result.requires_clarification is True
    assert result.confidence == 0.4


# ---------------------------------------------------------------------------
# detect() — fallback paths
# ---------------------------------------------------------------------------


async def test_unknown_intent_returns_fallback_with_clarification(router: IntentRouter) -> None:
    llm_fn = AsyncMock(return_value='{"intent": "nonsense_intent", "confidence": 0.95}')
    result = await router.detect("???", [], llm_fn, Mock())
    assert result.name == "unknown"
    assert result.requires_clarification is True


async def test_invalid_json_falls_back_to_keyword_detector(router: IntentRouter) -> None:
    llm_fn = AsyncMock(return_value="this is not json")
    # "complaint" is a dissatisfaction keyword in MockIntentDetector.
    result = await router.detect("I have a complaint", [], llm_fn, Mock())
    assert result.confidence == 0.5
    assert result.name == "customer_dissatisfaction_inquiry"


# ---------------------------------------------------------------------------
# detect() — known intents + custom threshold
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("intent_name", list(_KNOWN_INTENTS.keys()))
async def test_all_known_intents_reachable(router: IntentRouter, intent_name: str) -> None:
    llm_fn = AsyncMock(return_value=f'{{"intent": "{intent_name}", "confidence": 0.9}}')
    result = await router.detect("anything", [], llm_fn, Mock())
    assert result.name == intent_name
    assert result.agent_name == _KNOWN_INTENTS[intent_name].agent_name


async def test_custom_threshold_honored() -> None:
    strict_router = IntentRouter(threshold=0.95)
    # 0.85 passes the default 0.7 threshold but fails the strict 0.95 threshold.
    assert 0.85 > CONFIDENCE_THRESHOLD
    llm_fn = AsyncMock(return_value='{"intent": "book_service_appointment", "confidence": 0.85}')
    result = await strict_router.detect("book me a slot", [], llm_fn, Mock())
    assert result.requires_clarification is True
