"""Tests for ConversationOrchestrator."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import (
    AgentConfig,
    ContextLimitConfig,
    ConversationRequest,
    ConversationResponse,
    Message,
    MessageRole,
    PersonaConstraints,
)

_TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


def _make_request(content: str = "Hello") -> ConversationRequest:
    return ConversationRequest(
        conversation_id="conv-test",
        agent_config=AgentConfig(
            id="agent-1",
            name="Bot",
            persona="Helpful bot",
            greeting="Hi!",
        ),
        messages=[Message(role=MessageRole.USER, content=content)],
    )


def test_orchestrator_instantiates() -> None:
    orch = ConversationOrchestrator()
    assert orch is not None


@pytest.mark.asyncio
async def test_process_message_returns_mocked_llm_reply(mock_good_intent: Any) -> None:
    orch = ConversationOrchestrator()
    mock_reply = '[Mocked LLM] I received: "Hello there"'

    with patch.object(ConversationOrchestrator, "_call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_reply
        response = await orch.process_message(_make_request("Hello there"))

        assert response.conversation_id == "conv-test"
        assert response.reply.role == MessageRole.ASSISTANT
        assert response.reply.content == mock_reply


@pytest.mark.asyncio
async def test_process_message_returns_error_on_empty_messages() -> None:
    req = ConversationRequest(
        conversation_id="conv-empty",
        agent_config=AgentConfig(
            id="agent-1",
            name="Bot",
            persona="Helpful bot",
            greeting="Hi!",
        ),
        messages=[],
    )
    orch = ConversationOrchestrator()
    response = await orch.process_message(req)
    assert response.reply.role == MessageRole.ASSISTANT
    assert response.status == "error"
    assert "No user message content found" in response.error


@pytest.mark.asyncio
async def test_process_message_timeout_handling(mock_good_intent: Any) -> None:
    # Use settings with a very short timeout for testing
    from taskorbit.config import Settings

    settings = Settings(llm_timeout_seconds=0.01)
    orch = ConversationOrchestrator(settings=settings)

    # Mock _call_llm to sleep longer than the timeout
    async def slow_llm(*args: Any, **kwargs: Any) -> str:
        await asyncio.sleep(1.0)
        return "too slow"

    with patch.object(ConversationOrchestrator, "_call_llm", side_effect=slow_llm):
        response = await orch.process_message(_make_request())
        assert response.status == "error"
        assert "timed out after 0.01 seconds" in response.error
        assert "trouble connecting to my brain" in response.reply.content


# ---------------------------------------------------------------------------
# conversation_errors_total metric
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_increments_conversation_errors_total(mock_good_intent: Any) -> None:
    from taskorbit.config import Settings

    settings = Settings(llm_timeout_seconds=0.01)
    orch = ConversationOrchestrator(settings=settings)
    mock_metrics = MagicMock()

    async def slow_llm(*args: Any, **kwargs: Any) -> str:
        await asyncio.sleep(1.0)
        return "too slow"

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        with patch.object(ConversationOrchestrator, "_call_llm", side_effect=slow_llm):
            response = await orch.process_message(_make_request())

    assert response.status == "error"
    mock_metrics.conversation_errors_total.labels(error_type="llm_timeout").inc.assert_called_once()


@pytest.mark.asyncio
async def test_runtime_error_increments_conversation_errors_total(mock_good_intent: Any) -> None:
    orch = ConversationOrchestrator()
    mock_metrics = MagicMock()

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        with patch.object(
            ConversationOrchestrator,
            "_call_llm",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected boom"),
        ):
            response = await orch.process_message(_make_request())

    assert response.status == "error"
    mock_metrics.conversation_errors_total.labels(
        error_type="runtime_error"
    ).inc.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_input_increments_conversation_errors_total() -> None:
    orch = ConversationOrchestrator()
    mock_metrics = MagicMock()

    empty_req = ConversationRequest(
        conversation_id="conv-empty",
        agent_config=AgentConfig(id="a", name="Bot", persona="p", greeting="hi"),
        messages=[],
    )

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        response = await orch.process_message(empty_req)

    assert response.status == "error"
    mock_metrics.conversation_errors_total.labels(
        error_type="invalid_input"
    ).inc.assert_called_once()


# ---------------------------------------------------------------------------
# _build_system_prompt + persona_constraints
# ---------------------------------------------------------------------------

# These tests verify that the orchestrator correctly appends
# persona constraints using the new imperative headers (CORE CONSTRAINT).


def _agent_with_constraints(constraints: PersonaConstraints | None) -> AgentConfig:
    return AgentConfig(
        id="agent-1",
        name="John",
        persona="TechStore customer support.",
        greeting="Hi!",
        persona_constraints=constraints,
    )


def test_build_system_prompt_without_constraints_unchanged() -> None:
    """With no persona_constraints the prompt is exactly the existing format."""
    orch = ConversationOrchestrator()
    prompt = orch._build_system_prompt(_agent_with_constraints(None), active_tool=None)
    assert prompt == (
        "You are John.\nPersona: TechStore customer support.\n"
        "Keep replies brief and conversational, at most two short sentences. "
        "Ask for at most one missing detail at a time."
    )


def test_build_system_prompt_includes_persona_constraints() -> None:
    """Populated constraints append scope, out_of_scope, and refusal_template lines."""
    constraints = PersonaConstraints(
        scope="TechStore customer service: orders, returns, accounts.",
        out_of_scope=["therapy", "legal advice"],
        refusal_template="I can only help with TechStore questions.",
    )
    orch = ConversationOrchestrator()
    prompt = orch._build_system_prompt(_agent_with_constraints(constraints), active_tool=None)

    # Guardrails now lead the prompt (#168); the persona body is preserved below it.
    assert prompt.startswith("TOP PRIORITY - STAY IN ROLE:")
    assert "You are John.\nPersona: TechStore customer support." in prompt
    # Asserting against the new imperative headers
    assert (
        "CORE CONSTRAINT - Authorized Scope: TechStore customer service: orders, returns, accounts."
        in prompt
    )
    assert (
        "CORE CONSTRAINT - Forbidden Topics (you MUST politely refuse and redirect): therapy, legal advice"
        in prompt
    )
    assert (
        'REQUIRED REFUSAL PHRASE (use this for redirection): "I can only help with TechStore questions."'
        in prompt
    )


def test_build_system_prompt_empty_constraints_object_is_noop() -> None:
    """A PersonaConstraints with every field empty leaves the prompt unchanged."""
    orch = ConversationOrchestrator()
    prompt = orch._build_system_prompt(
        _agent_with_constraints(PersonaConstraints()), active_tool=None
    )
    assert prompt == (
        "You are John.\nPersona: TechStore customer support.\n"
        "Keep replies brief and conversational, at most two short sentences. "
        "Ask for at most one missing detail at a time."
    )


# ---------------------------------------------------------------------------
# _truncate_messages — conversation-history FIFO cap (LLM memory safeguards)
# ---------------------------------------------------------------------------


def _msg(role: MessageRole, content: str) -> Message:
    return Message(role=role, content=content)


def _conversation(count: int) -> list[Message]:
    """Build alternating user/assistant turns: u0, a0, u1, a1, ..."""
    out: list[Message] = []
    for i in range(count):
        role = MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT
        out.append(_msg(role, f"msg-{i}"))
    return out


def test_truncate_messages_returns_unchanged_when_no_context_limit() -> None:
    """No config → full history is passed through verbatim."""
    orch = ConversationOrchestrator()
    msgs = _conversation(20)
    assert orch._truncate_messages(msgs, None) == msgs


def test_truncate_messages_returns_unchanged_when_under_limit() -> None:
    """History smaller than the cap is returned untouched."""
    orch = ConversationOrchestrator()
    msgs = _conversation(10)
    result = orch._truncate_messages(msgs, ContextLimitConfig(type="message_count", value=50))
    assert result == msgs


def test_truncate_messages_drops_oldest_fifo_when_over_limit() -> None:
    """FIFO: oldest non-system messages are removed first."""
    orch = ConversationOrchestrator()
    msgs = _conversation(100)
    result = orch._truncate_messages(msgs, ContextLimitConfig(type="message_count", value=10))
    assert len(result) == 10
    # The first kept message should be msg-90; last should be msg-99.
    assert result[0].content == "msg-90"
    assert result[-1].content == "msg-99"


def test_truncate_messages_preserves_system_prompt_at_minimum_limit() -> None:
    """Acceptance criterion: system prompt is NEVER dropped (schema min limit = 10)."""
    orch = ConversationOrchestrator()
    system = _msg(MessageRole.SYSTEM, "You are TaskOrbit.")
    msgs = [system, *_conversation(30)]
    result = orch._truncate_messages(msgs, ContextLimitConfig(type="message_count", value=10))
    # System prompt survives + exactly 10 most recent conversation messages kept.
    assert result[0] is system
    assert len(result) == 11
    assert result[1].content == "msg-20"
    assert result[-1].content == "msg-29"


def test_truncate_messages_preserves_multiple_system_messages() -> None:
    """All system messages are protected regardless of position."""
    orch = ConversationOrchestrator()
    sys1 = _msg(MessageRole.SYSTEM, "sys-1")
    sys2 = _msg(MessageRole.SYSTEM, "sys-2")
    # 30 non-system messages, split around a second system message.
    msgs = [sys1, *_conversation(15), sys2, *_conversation(15)]
    result = orch._truncate_messages(msgs, ContextLimitConfig(type="message_count", value=10))
    # Both system messages present; only the last 10 non-system kept.
    system_results = [m for m in result if m.role == MessageRole.SYSTEM]
    other_results = [m for m in result if m.role != MessageRole.SYSTEM]
    assert system_results == [sys1, sys2]
    assert len(other_results) == 10


def test_truncate_messages_logs_truncation_event() -> None:
    """Truncation must emit a structured log line with counts (for observability)."""
    orch = ConversationOrchestrator()
    msgs = _conversation(30)
    with patch("taskorbit.orchestration.logger") as mock_logger:
        orch._truncate_messages(msgs, ContextLimitConfig(type="message_count", value=10))
        mock_logger.info.assert_called_once()
        call_kwargs = mock_logger.info.call_args.kwargs
        assert mock_logger.info.call_args.args[0] == "message_truncation_applied"
        assert call_kwargs["original_count"] == 30
        assert call_kwargs["trimmed_count"] == 10
        assert call_kwargs["dropped_count"] == 20


def test_truncate_messages_does_not_log_when_under_limit() -> None:
    """No truncation → no log noise."""
    orch = ConversationOrchestrator()
    msgs = _conversation(5)
    with patch("taskorbit.orchestration.logger") as mock_logger:
        orch._truncate_messages(msgs, ContextLimitConfig(type="message_count", value=50))
        mock_logger.info.assert_not_called()


def test_context_limit_rejects_unsupported_strategy() -> None:
    """Only 'message_count' is enforced this sprint; the schema rejects others."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ContextLimitConfig(type="token_threshold", value=100)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Routing pipeline (#8 Task 7)
# ---------------------------------------------------------------------------


def _intent_result(
    name: str = "book_service_appointment",
    agent_name: str = "sales",
    confidence: float = 0.9,
    requires_clarification: bool = False,
    required_inputs: list[dict[str, Any]] | None = None,
) -> Any:
    from taskorbit.intent import IntentResult

    return IntentResult(
        name=name,
        description="test",
        agent_name=agent_name,
        required_inputs=required_inputs or [],
        confidence=confidence,
        requires_clarification=requires_clarification,
    )


@pytest.mark.asyncio
async def test_clarification_short_circuits_pipeline() -> None:
    """Low confidence intent skips LLM call and returns CLARIFICATION status."""
    from taskorbit.intent import _CLARIFICATION_REPLY

    orch = ConversationOrchestrator()
    low_conf = _intent_result(confidence=0.3, requires_clarification=True)

    with patch.object(orch._intent_router, "detect", new_callable=AsyncMock) as mock_detect:
        mock_detect.return_value = low_conf
        with patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock
        ) as mock_llm:
            response = await orch.process_message(_make_request("uhh maybe?"))

    assert response.status == "clarification"
    assert response.selected_agent == ""
    assert response.reply.content == _CLARIFICATION_REPLY
    mock_llm.assert_not_called()  # short-circuit means no LLM call


@pytest.mark.asyncio
async def test_routed_agent_matches_intent_agent_name() -> None:
    """selected_agent in response mirrors intent.agent_name from the router."""
    orch = ConversationOrchestrator()
    intent = _intent_result(
        name="customer_dissatisfaction_inquiry", agent_name="customer_dissatisfaction"
    )

    req = ConversationRequest(
        conversation_id="conv-test",
        agent_config=AgentConfig(id="agent-1", name="Bot", persona="Helpful bot", greeting="Hi!"),
        messages=[Message(role=MessageRole.USER, content="I'm unhappy")],
        selected_agent="sales",  # turn 2+: entry agent was returned on turn 1
    )

    with patch.object(orch._intent_router, "detect", new_callable=AsyncMock) as mock_detect:
        mock_detect.return_value = intent
        with patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
        ):
            response = await orch.process_message(req)

    assert response.selected_intent == "customer_dissatisfaction_inquiry"
    assert response.selected_agent == "customer_dissatisfaction"


@pytest.mark.asyncio
async def test_agent_transfer_dispatch_sets_tool_invoked() -> None:
    """When an agent_transfer tool fires, response.tool_invoked is populated."""
    from taskorbit.slots.models import SlotExtractionResult, SlotValue
    from taskorbit.types import ConfirmationConfig, ToolDefinition, ToolType

    orch = ConversationOrchestrator()
    intent = _intent_result(
        required_inputs=[{"name": "caller_name", "type": "string", "required": True}]
    )
    transfer_tool = ToolDefinition(
        id="transfer-1",
        name="agent_transfer",
        type=ToolType.AGENT_TRANSFER,
        description="hand off",
        confirmation=ConfirmationConfig(required=False, prompt=""),
        parameters={"targets": ["technical_support"]},
    )
    slot_result = SlotExtractionResult(
        filled={"caller_name": SlotValue(name="caller_name", value="Asad", slot_type="string")},
        missing=[],
    )

    with (
        patch.object(orch._intent_router, "detect", new_callable=AsyncMock, return_value=intent),
        patch.object(ConversationOrchestrator, "_select_active_tool", return_value=transfer_tool),
        patch.object(
            ConversationOrchestrator,
            "_extract_slots",
            new_callable=AsyncMock,
            return_value=slot_result,
        ),
        patch.object(
            ConversationOrchestrator,
            "_dispatch_tool",
            new_callable=AsyncMock,
            return_value=({"transferred_to": "technical_support", "history_preserved": True}, 0.0),
        ),
        patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
        ),
    ):
        response = await orch.process_message(_make_request("transfer me"))

    assert response.tool_invoked is not None
    assert response.tool_invoked.type == ToolType.AGENT_TRANSFER


@pytest.mark.asyncio
async def test_unknown_intent_falls_back_via_clarification() -> None:
    """When the LLM returns no matching intent, the router's _FALLBACK_RESULT
    surfaces as a clarification response — no 500 error, no LLM call for reply."""
    from taskorbit.intent import _CLARIFICATION_REPLY, _FALLBACK_RESULT

    orch = ConversationOrchestrator()

    with patch.object(
        orch._intent_router, "detect", new_callable=AsyncMock, return_value=_FALLBACK_RESULT
    ):
        with patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock
        ) as mock_llm:
            response = await orch.process_message(_make_request("blibber blabber"))

    assert response.status == "clarification"
    assert response.selected_intent == "unknown"
    assert response.selected_agent == ""
    assert response.reply.content == _CLARIFICATION_REPLY
    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_external_api_dispatch_passes_full_config_plus_args() -> None:
    """#66 wiring: EXTERNAL_API tools receive the full tool.parameters config
    merged with the extracted slot values under an `args` key, so the adapter
    can substitute templates and validate args without the orchestrator having
    to understand the adapter's internal contract."""
    from taskorbit.slots.models import SlotExtractionResult, SlotValue
    from taskorbit.types import ConfirmationConfig, ToolDefinition, ToolType

    orch = ConversationOrchestrator()
    intent = _intent_result(required_inputs=[{"name": "city", "type": "string", "required": True}])
    external_api_tool = ToolDefinition(
        id="lookup-weather",
        name="lookup_weather",
        type=ToolType.EXTERNAL_API,
        description="weather lookup",
        confirmation=ConfirmationConfig(required=False, prompt=""),
        parameters={
            "request": {"method": "GET", "url": "https://x/{{args.city}}"},
            "response": {"extract": {"temp": "current.temp_c"}},
            "args_schema": {
                "type": "object",
                "required": ["city"],
                "properties": {"city": {"type": "string"}},
            },
        },
    )
    slot_result = SlotExtractionResult(
        filled={"city": SlotValue(name="city", value="Berlin", slot_type="string")},
        missing=[],
    )

    dispatch_calls: list[dict[str, Any]] = []

    async def _capture_dispatch(
        _self: ConversationOrchestrator,
        _tool: ToolDefinition,
        ctx: dict[str, Any],
        **_kwargs: Any,
    ) -> tuple[dict[str, Any], float]:
        dispatch_calls.append(ctx)
        return {"status": 200, "data": {"temp": 18.3}}, 0.0

    with (
        patch.object(orch._intent_router, "detect", new_callable=AsyncMock, return_value=intent),
        patch.object(
            ConversationOrchestrator, "_select_active_tool", return_value=external_api_tool
        ),
        patch.object(
            ConversationOrchestrator,
            "_extract_slots",
            new_callable=AsyncMock,
            return_value=slot_result,
        ),
        patch.object(
            ConversationOrchestrator,
            "_dispatch_tool",
            new=_capture_dispatch,
        ),
        patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
        ),
    ):
        response = await orch.process_message(_make_request("weather please"))

    assert response.tool_invoked is not None
    assert response.tool_invoked.type == ToolType.EXTERNAL_API
    # The dispatch context must carry the tool's static config (so the adapter
    # can find request/response/args_schema) AND the LLM-extracted args under
    # the `args` key (so {{args.city}} substitutes correctly).
    assert len(dispatch_calls) == 1
    ctx = dispatch_calls[0]
    assert "request" in ctx and ctx["request"]["method"] == "GET"
    assert "response" in ctx
    assert "args_schema" in ctx
    assert ctx["args"] == {"city": "Berlin"}


def test_external_api_requires_args_helper() -> None:
    """Helper returns True only for EXTERNAL_API tools whose args_schema
    declares a non-empty ``required`` list. Everything else, including
    other tool types and empty/missing required lists, returns False."""
    from taskorbit.orchestration import _external_api_requires_args
    from taskorbit.types import ConfirmationConfig, ToolDefinition, ToolType

    def _mk(tool_type: ToolType, params: dict[str, Any] | None) -> ToolDefinition:
        return ToolDefinition(
            id="t",
            name="t",
            type=tool_type,
            description="d",
            confirmation=ConfirmationConfig(required=False, prompt=""),
            parameters=params or {},
        )

    with_required = _mk(
        ToolType.EXTERNAL_API,
        {"args_schema": {"type": "object", "required": ["city"], "properties": {}}},
    )
    empty_required = _mk(
        ToolType.EXTERNAL_API,
        {"args_schema": {"type": "object", "required": [], "properties": {}}},
    )
    no_schema = _mk(ToolType.EXTERNAL_API, {})
    non_api = _mk(
        ToolType.DATA_EXTRACTION,
        {"args_schema": {"type": "object", "required": ["x"], "properties": {}}},
    )

    assert _external_api_requires_args(with_required) is True
    assert _external_api_requires_args(empty_required) is False
    assert _external_api_requires_args(no_schema) is False
    assert _external_api_requires_args(non_api) is False


def test_build_system_prompt_injects_tool_data() -> None:
    """When tool_data is passed, its JSON is injected into the system prompt
    with an instruction telling the LLM to use it instead of prior knowledge.
    This is what lets an external_api result (e.g. current time from
    timeapi.io) actually reach the LLM."""
    from taskorbit.types import (
        AgentConfig as _AC,
    )
    from taskorbit.types import (
        ConfirmationConfig,
        ToolDefinition,
        ToolType,
    )

    orch = ConversationOrchestrator()
    config = _AC(id="a", name="a", persona="p", greeting="g")
    tool = ToolDefinition(
        id="t",
        name="get_time",
        type=ToolType.EXTERNAL_API,
        description="Returns current time",
        confirmation=ConfirmationConfig(required=False, prompt=""),
        parameters={},
    )
    tool_data = {"status": 200, "data": {"dateTime": "2026-07-08T14:30:00"}}

    prompt = orch._build_system_prompt(config, tool, None, routed_agent=None, tool_data=tool_data)

    assert "Tool result" in prompt
    assert "dateTime" in prompt
    assert "2026-07-08T14:30:00" in prompt
    assert "do NOT answer from prior knowledge" in prompt


def test_build_system_prompt_omits_tool_data_when_aborted() -> None:
    """An aborted tool_data payload (e.g. user rejected a confirmation)
    must NOT be injected: the LLM should not see partial or void tool
    output as authoritative ground truth."""
    from taskorbit.types import (
        AgentConfig as _AC,
    )
    from taskorbit.types import (
        ConfirmationConfig,
        ToolDefinition,
        ToolType,
    )

    orch = ConversationOrchestrator()
    config = _AC(id="a", name="a", persona="p", greeting="g")
    tool = ToolDefinition(
        id="t",
        name="t",
        type=ToolType.EXTERNAL_API,
        description="d",
        confirmation=ConfirmationConfig(required=False, prompt=""),
        parameters={},
    )

    prompt = orch._build_system_prompt(
        config, tool, None, routed_agent=None, tool_data={"aborted": True}
    )

    assert "Tool result" not in prompt
    assert "aborted" not in prompt


@pytest.mark.asyncio
async def test_no_arg_external_api_dispatches_and_llm_sees_result() -> None:
    """End-to-end for Carl's bug: an EXTERNAL_API tool with no required args
    (e.g. Current_Date_and_Time_Tool) must dispatch BEFORE the LLM call,
    and the resulting tool_data must land in the system prompt so the LLM
    can quote a fresh value instead of answering from its training cutoff."""
    from taskorbit.slots.models import SlotExtractionResult
    from taskorbit.types import ConfirmationConfig, ToolDefinition, ToolType

    orch = ConversationOrchestrator()
    intent = _intent_result(required_inputs=[])
    tool = ToolDefinition(
        id="current-time",
        name="Current_Date_and_Time_Tool",
        type=ToolType.EXTERNAL_API,
        description="Returns current time in Europe/Berlin",
        confirmation=ConfirmationConfig(required=False, prompt=""),
        parameters={
            "request": {
                "method": "GET",
                "url": "https://timeapi.io/api/Time/current/zone?timeZone=Europe/Berlin",
            },
            "response": {"extract": {"dateTime": "dateTime"}},
            "args_schema": {"type": "object", "required": [], "properties": {}},
        },
    )
    slot_result = SlotExtractionResult(filled={}, missing=[])

    async def _fake_dispatch(
        _self: ConversationOrchestrator,
        _tool: ToolDefinition,
        _ctx: dict[str, Any],
        **_kwargs: Any,
    ) -> tuple[dict[str, Any], float]:
        return {"status": 200, "data": {"dateTime": "2026-07-08T14:30:00"}}, 0.0

    seen_prompts: list[str] = []

    async def _capture_llm(
        _self: ConversationOrchestrator,
        system_prompt: str,
        *_a: Any,
        **_kw: Any,
    ) -> str:
        seen_prompts.append(system_prompt)
        return "It is 2026-07-08 14:30 in Berlin."

    with (
        patch.object(orch._intent_router, "detect", new_callable=AsyncMock, return_value=intent),
        patch.object(ConversationOrchestrator, "_select_active_tool", return_value=tool),
        patch.object(
            ConversationOrchestrator,
            "_extract_slots",
            new_callable=AsyncMock,
            return_value=slot_result,
        ),
        patch.object(ConversationOrchestrator, "_dispatch_tool", new=_fake_dispatch),
        patch.object(ConversationOrchestrator, "_call_llm", new=_capture_llm),
    ):
        response = await orch.process_message(_make_request("what time is it?"))

    assert response.tool_invoked is not None
    assert response.tool_invoked.type == ToolType.EXTERNAL_API
    assert len(seen_prompts) == 1
    assert "2026-07-08T14:30:00" in seen_prompts[0]
    assert "Tool result" in seen_prompts[0]


@pytest.mark.asyncio
async def test_process_message_confirmation_flow(mock_good_intent: Any) -> None:
    """AC #49: End-to-end confirmation flow (pending -> approved -> rejected)."""
    from taskorbit.types import (
        ConfirmationConfig,
        ConversationStatus,
        ToolDefinition,
        ToolType,
    )

    orch = ConversationOrchestrator()
    req = _make_request("John")
    # Add a tool that requires confirmation
    req.agent_config.tools = [
        ToolDefinition(
            id="tool-1",
            name="collect_info",
            type=ToolType.DATA_EXTRACTION,
            description="Collect info",
            confirmation=ConfirmationConfig(required=True, prompt="Confirm save?"),
        )
    ]

    # Mock intent to have required inputs so the tool triggers
    mock_good_intent.required_inputs = [{"name": "name", "type": "string", "required": True}]

    with patch.object(ConversationOrchestrator, "_call_llm", new_callable=AsyncMock) as mock_llm:
        # 1. First turn: slots complete, should trigger confirmation
        mock_llm.return_value = "Saving info..."
        from taskorbit.slots import SlotExtractionResult

        with patch.object(
            ConversationOrchestrator, "_extract_slots", new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = SlotExtractionResult(
                filled={"name": MagicMock(value="John")}, missing=[]
            )

            response = await orch.process_message(req)

            assert response.status == ConversationStatus.CONFIRMATION_REQUIRED
            assert response.confirmation is not None
            assert response.confirmation.confirmation_id == "tool-1"
            assert response.confirmation.action == "collect_info"

        # 2. Second turn: confirmed
        req.confirmation_id = "tool-1"
        req.decision = "confirm"
        with patch.object(
            ConversationOrchestrator, "_extract_slots", new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = SlotExtractionResult(
                filled={"name": MagicMock(value="John")}, missing=[]
            )
            with patch.object(
                ConversationOrchestrator, "_dispatch_tool", new_callable=AsyncMock
            ) as mock_dispatch:
                mock_dispatch.return_value = ({"saved": True}, 0.0)

                response = await orch.process_message(req)

                assert response.status == ConversationStatus.SUCCESS
                assert response.tool_invoked.id == "tool-1"
                mock_dispatch.assert_called_once()

        # 3. Third turn: rejected
        req.decision = "reject"
        with patch.object(
            ConversationOrchestrator, "_extract_slots", new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = SlotExtractionResult(
                filled={"name": MagicMock(value="John")}, missing=[]
            )
            with patch.object(
                ConversationOrchestrator, "_dispatch_tool", new_callable=AsyncMock
            ) as mock_dispatch:
                response = await orch.process_message(req)

                assert response.status == ConversationStatus.REJECTED
                assert "cancelled" in response.reply.content.lower()
                mock_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# process_message_stream
# ---------------------------------------------------------------------------


async def _fake_llm_chunks(*tokens: str):
    for token in tokens:
        yield token


@pytest.mark.asyncio
async def test_process_message_stream_yields_chunks_then_response(
    mock_good_intent: Any,
) -> None:
    orch = ConversationOrchestrator()

    with patch.object(
        ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="{}"
    ):
        with patch.object(
            ConversationOrchestrator,
            "_call_llm_stream",
            return_value=_fake_llm_chunks("Hello ", "world!"),
        ):
            events = []
            async for event in orch.process_message_stream(_make_request("hi")):
                events.append(event)

    text_chunks = [e for e in events if isinstance(e, str)]
    responses = [e for e in events if not isinstance(e, str)]

    assert text_chunks == ["Hello ", "world!"]
    assert len(responses) == 1
    final = responses[0]
    assert final.reply.content == "Hello world!"
    assert final.reply.role == MessageRole.ASSISTANT
    assert final.conversation_id == "conv-test"


@pytest.mark.asyncio
async def test_process_message_stream_final_response_carries_metadata(
    mock_good_intent: Any,
) -> None:
    orch = ConversationOrchestrator()

    with patch.object(
        ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="{}"
    ):
        with patch.object(
            ConversationOrchestrator,
            "_call_llm_stream",
            return_value=_fake_llm_chunks("ok"),
        ):
            events = []
            async for event in orch.process_message_stream(_make_request("hi")):
                events.append(event)

    final = next(e for e in events if not isinstance(e, str))
    assert final.selected_intent == mock_good_intent.name
    assert final.status == "success"
    assert final.intent_confidence == 0.9


@pytest.mark.asyncio
async def test_process_message_stream_yields_error_response_on_empty_messages() -> None:
    orch = ConversationOrchestrator()
    req = ConversationRequest(
        conversation_id="conv-empty",
        agent_config=AgentConfig(id="a", name="Bot", persona="p", greeting="Hi!"),
        messages=[],
    )

    events = []
    async for event in orch.process_message_stream(req):
        events.append(event)

    assert len(events) == 1
    assert events[0].status == "error"
    assert "No user message content found" in events[0].error


@pytest.mark.asyncio
async def test_process_message_stream_clarification_yields_response_without_chunks() -> None:
    from taskorbit.intent import _CLARIFICATION_REPLY, _FALLBACK_RESULT

    orch = ConversationOrchestrator()

    with patch.object(
        orch._intent_router, "detect", new_callable=AsyncMock, return_value=_FALLBACK_RESULT
    ):
        with patch.object(ConversationOrchestrator, "_call_llm_stream") as mock_stream:
            events = []
            async for event in orch.process_message_stream(_make_request("???")):
                events.append(event)

    text_chunks = [e for e in events if isinstance(e, str)]
    responses = [e for e in events if not isinstance(e, str)]

    assert text_chunks == []
    assert len(responses) == 1
    assert responses[0].status == "clarification"
    assert responses[0].reply.content == _CLARIFICATION_REPLY
    mock_stream.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_stream_confirmation_required_does_not_dispatch_tool(
    mock_good_intent: Any,
) -> None:
    """Confirmation-required tool must block dispatch and emit CONFIRMATION_REQUIRED."""
    from taskorbit.slots import SlotExtractionResult
    from taskorbit.types import (
        ConfirmationConfig,
        ConversationStatus,
        ToolDefinition,
        ToolType,
    )

    orch = ConversationOrchestrator()
    req = _make_request("book me")
    req.agent_config.tools = [
        ToolDefinition(
            id="tool-confirm",
            name="BookAppointment",
            type=ToolType.DATA_EXTRACTION,
            description="Book",
            confirmation=ConfirmationConfig(required=True, prompt="Confirm booking?"),
        )
    ]
    mock_good_intent.required_inputs = [{"name": "date", "type": "string", "required": True}]

    with patch.object(
        ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="{}"
    ):
        with patch.object(
            ConversationOrchestrator,
            "_call_llm_stream",
            return_value=_fake_llm_chunks("Sure, I can book that."),
        ):
            with patch.object(
                ConversationOrchestrator, "_extract_slots", new_callable=AsyncMock
            ) as mock_extract:
                mock_extract.return_value = SlotExtractionResult(
                    filled={"date": MagicMock(value="tomorrow")}, missing=[]
                )
                with patch.object(
                    ConversationOrchestrator, "_dispatch_tool", new_callable=AsyncMock
                ) as mock_dispatch:
                    events = []
                    async for event in orch.process_message_stream(req):
                        events.append(event)

    responses = [e for e in events if not isinstance(e, str)]
    assert len(responses) == 1
    assert responses[0].status == ConversationStatus.CONFIRMATION_REQUIRED
    assert responses[0].confirmation is not None
    assert responses[0].confirmation.confirmation_id == "tool-confirm"
    mock_dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_stream_mid_stream_error_yields_error_response(
    mock_good_intent: Any,
) -> None:
    """A provider that raises mid-stream produces an error ConversationResponse
    with the #197 polite reply, the llm_provider_error metric label, and the
    original SDK message in the .error field for on-call debugging."""
    from taskorbit.integrations.llm.errors import LLMAPIError

    orch = ConversationOrchestrator()
    mock_metrics = MagicMock()

    async def _failing_stream(*args: Any, **kwargs: Any):
        yield "Hello "
        raise LLMAPIError("provider blew up")

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        with patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="{}"
        ):
            with patch.object(
                ConversationOrchestrator, "_call_llm_stream", return_value=_failing_stream()
            ):
                events = []
                async for event in orch.process_message_stream(_make_request("hi")):
                    events.append(event)

    # The partial "Hello " chunk may or may not have been yielded before the
    # error; what must always be true is that the final event is an error response
    # and it carries the polite reply + metric label required by #197.
    assert len(events) >= 1
    final = events[-1]
    assert not isinstance(final, str)
    assert final.status == "error"
    assert final.reply is not None
    assert "language model provider" in final.reply.content
    assert final.error is not None
    assert "provider blew up" in final.error
    mock_metrics.conversation_errors_total.labels(
        error_type="llm_provider_error"
    ).inc.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_stream_dispatches_tool_when_slots_complete(
    mock_good_intent: Any,
) -> None:
    """Tool is dispatched (once) when all required slots are filled."""
    from taskorbit.slots import SlotExtractionResult
    from taskorbit.types import ConversationStatus, ToolDefinition, ToolType

    orch = ConversationOrchestrator()
    req = _make_request("book me")
    req.agent_config.tools = [
        ToolDefinition(
            id="tool-data",
            name="SaveData",
            type=ToolType.DATA_EXTRACTION,
            description="Save",
        )
    ]
    mock_good_intent.required_inputs = [{"name": "name", "type": "string", "required": True}]

    with patch.object(
        ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="{}"
    ):
        with patch.object(
            ConversationOrchestrator,
            "_call_llm_stream",
            return_value=_fake_llm_chunks("Saved!"),
        ):
            with patch.object(
                ConversationOrchestrator, "_extract_slots", new_callable=AsyncMock
            ) as mock_extract:
                mock_extract.return_value = SlotExtractionResult(
                    filled={"name": MagicMock(value="Alice")}, missing=[]
                )
                with patch.object(
                    ConversationOrchestrator, "_dispatch_tool", new_callable=AsyncMock
                ) as mock_dispatch:
                    mock_dispatch.return_value = ({"saved": True}, 0.0)
                    events = []
                    async for event in orch.process_message_stream(req):
                        events.append(event)

    responses = [e for e in events if not isinstance(e, str)]
    assert len(responses) == 1
    assert responses[0].status == ConversationStatus.SUCCESS
    assert responses[0].tool_invoked is not None
    mock_dispatch.assert_called_once()


# ---------------------------------------------------------------------------
# _user_requested_end_call — keyword detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "goodbye",
        "Goodbye!",
        "GOODBYE",
        "bye bye",
        "end the call",
        "end this call",
        "hang up",
        "hangup",
        "please end the call",
        "please hang up",
        "i want to end the call",
        "i want to hang up",
        "end the conversation",
        "wrap up the call",
        "that's all i needed",
        "no more questions",
        "i'm done for now",
        "done for today",
        "i think that's all",
        # Substring containment — the critical case from the bug report
        "can you please end the call?",
        "okay, goodbye then",
        "I have no more questions, thanks",
    ],
)
def test_user_requested_end_call_matches_signals(phrase: str) -> None:
    orch = ConversationOrchestrator()
    assert orch._user_requested_end_call(phrase) is True


@pytest.mark.parametrize(
    "phrase",
    [
        "hello",
        "what are your hours?",
        "I need help with my account",
        "can you call me back?",
        "tell me more",
        "yes please",
        "not yet",
        "",
    ],
)
def test_user_requested_end_call_does_not_match_normal_phrases(phrase: str) -> None:
    orch = ConversationOrchestrator()
    assert orch._user_requested_end_call(phrase) is False


@pytest.mark.parametrize(
    "phrase",
    [
        "please don't end the call",
        "don't hang up",
        "dont hang up",
        "do not end the call",
        "please don't hang up",
        "won't end the call",
        "will not hang up",
        "can't end the call",
        "cannot hang up",
        "never end the call",
        "not goodbye",
    ],
)
def test_user_requested_end_call_negation_guard(phrase: str) -> None:
    """Negated farewell phrases must NOT trigger end-call detection."""
    orch = ConversationOrchestrator()
    assert orch._user_requested_end_call(phrase) is False


# ---------------------------------------------------------------------------
# End-call early exit in process_message
# ---------------------------------------------------------------------------


def _make_request_with_end_call_tool(content: str = "goodbye") -> ConversationRequest:
    from taskorbit.types import ConfirmationConfig, ToolDefinition, ToolType

    end_call_tool = ToolDefinition(
        id="end-1",
        name="end_call",
        type=ToolType.END_CALL,
        description="End the call",
        confirmation=ConfirmationConfig(required=False),
    )
    return ConversationRequest(
        conversation_id="conv-end",
        agent_config=AgentConfig(
            id="agent-1",
            name="Bot",
            persona="Helpful bot",
            greeting="Hi!",
            tools=[end_call_tool],
        ),
        messages=[Message(role=MessageRole.USER, content=content)],
    )


@pytest.mark.asyncio
async def test_end_call_returns_ended_status() -> None:
    """When user says goodbye and end_call tool is present, status is ENDED."""
    from taskorbit.types import ConversationStatus, ToolType

    orch = ConversationOrchestrator()
    with patch.object(
        ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="Goodbye!"
    ):
        with patch.object(
            ConversationOrchestrator,
            "_dispatch_tool",
            new_callable=AsyncMock,
            return_value=({}, 0.0),
        ):
            response = await orch.process_message(_make_request_with_end_call_tool("goodbye"))

    assert response.status == ConversationStatus.ENDED
    assert response.tool_invoked is not None
    assert response.tool_invoked.type == ToolType.END_CALL


@pytest.mark.asyncio
async def test_end_call_skips_intent_router() -> None:
    """Early exit means IntentRouter.detect is never called."""
    orch = ConversationOrchestrator()
    with patch.object(
        ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="Goodbye!"
    ):
        with patch.object(
            ConversationOrchestrator,
            "_dispatch_tool",
            new_callable=AsyncMock,
            return_value=({}, 0.0),
        ):
            with patch.object(orch._intent_router, "detect", new_callable=AsyncMock) as mock_detect:
                await orch.process_message(_make_request_with_end_call_tool("hang up please"))

    mock_detect.assert_not_called()


@pytest.mark.asyncio
async def test_end_call_not_triggered_without_tool(mock_good_intent: Any) -> None:
    """When agent has no end_call tool, farewell phrases go through normal pipeline."""
    orch = ConversationOrchestrator()
    with patch.object(
        ConversationOrchestrator,
        "_call_llm",
        new_callable=AsyncMock,
        return_value="How can I help?",
    ) as mock_llm:
        # _make_request has no end_call tool configured
        response = await orch.process_message(_make_request("goodbye"))

    assert response.status != "ended"
    assert mock_llm.called  # normal pipeline ran (may be called >1 for slot extraction + reply)


@pytest.mark.asyncio
async def test_end_call_not_triggered_by_non_farewell(mock_good_intent: Any) -> None:
    """End-call tool present but user does not say farewell → early exit does not fire.

    We patch _select_active_tool to None so the downstream dispatch path doesn't
    pick up the end_call step from book_service_appointment's workflow steps
    and obscure the early-exit assertion.
    """
    orch = ConversationOrchestrator()
    with patch.object(
        ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="Sure!"
    ):
        with patch.object(ConversationOrchestrator, "_select_active_tool", return_value=None):
            response = await orch.process_message(
                _make_request_with_end_call_tool("I need help with my order")
            )

    assert response.status != "ended"


@pytest.mark.asyncio
async def test_end_call_reply_is_llm_farewell() -> None:
    """The reply content comes from the LLM farewell, not a hardcoded string."""
    orch = ConversationOrchestrator()
    farewell_text = "It was great talking to you, take care!"
    with patch.object(
        ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value=farewell_text
    ):
        with patch.object(
            ConversationOrchestrator,
            "_dispatch_tool",
            new_callable=AsyncMock,
            return_value=({}, 0.0),
        ):
            response = await orch.process_message(_make_request_with_end_call_tool("goodbye"))

    assert response.reply.content == farewell_text


@pytest.mark.asyncio
async def test_end_call_uses_fallback_farewell_on_llm_timeout() -> None:
    """If the farewell LLM call times out, the call still ends with a hardcoded farewell."""
    from taskorbit.config import Settings
    from taskorbit.types import ConversationStatus

    orch = ConversationOrchestrator(settings=Settings(llm_timeout_seconds=0.01))

    async def slow_llm(*args: Any, **kwargs: Any) -> str:
        await asyncio.sleep(1.0)
        return "too slow"

    with patch.object(ConversationOrchestrator, "_call_llm", side_effect=slow_llm):
        with patch.object(
            ConversationOrchestrator,
            "_dispatch_tool",
            new_callable=AsyncMock,
            return_value=({}, 0.0),
        ):
            response = await orch.process_message(_make_request_with_end_call_tool("goodbye"))

    assert response.status == ConversationStatus.ENDED
    assert response.reply.content == "Goodbye! Take care."


@pytest.mark.asyncio
async def test_end_call_uses_fallback_farewell_on_llm_error() -> None:
    """If the farewell LLM call raises any error, the call still ends with a hardcoded farewell."""
    from taskorbit.types import ConversationStatus

    orch = ConversationOrchestrator()

    with patch.object(
        ConversationOrchestrator,
        "_call_llm",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM unavailable"),
    ):
        with patch.object(
            ConversationOrchestrator,
            "_dispatch_tool",
            new_callable=AsyncMock,
            return_value=({}, 0.0),
        ):
            response = await orch.process_message(_make_request_with_end_call_tool("hang up"))

    assert response.status == ConversationStatus.ENDED
    assert response.reply.content == "Goodbye! Take care."


# ---------------------------------------------------------------------------
# Intent locking across turns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intent_locked_when_current_intent_name_set(mock_good_intent: Any) -> None:
    """When current_intent_name matches a known intent and classifier agrees,
    the locked intent is reused (confidence=1.0) and logged as intent_locked."""
    from taskorbit.intent import _KNOWN_INTENTS

    orch = ConversationOrchestrator()
    locked_name = "technical_support_request"
    # Router returns low confidence for a different intent so the lock holds.
    low_conf_other = _intent_result(
        name="general_inquiry", agent_name="general_inquiry", confidence=0.5
    )

    req = ConversationRequest(
        conversation_id="conv-lock",
        agent_config=AgentConfig(id="a", name="Bot", persona="p", greeting="hi"),
        messages=[Message(role=MessageRole.USER, content="still having that error")],
        current_intent_name=locked_name,
        selected_agent="technical_support",  # turn 2+: agent active when lock was established
    )

    with patch.object(
        orch._intent_router, "detect", new_callable=AsyncMock, return_value=low_conf_other
    ):
        with patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
        ):
            response = await orch.process_message(req)

    assert response.selected_intent == locked_name
    assert response.selected_agent == _KNOWN_INTENTS[locked_name].agent_name


@pytest.mark.asyncio
async def test_intent_lock_broken_on_high_confidence_new_intent() -> None:
    """When a genuinely different intent arrives with confidence ≥ threshold,
    the lock is broken and the new intent is used."""
    orch = ConversationOrchestrator()
    high_conf_new = _intent_result(
        name="customer_dissatisfaction_inquiry",
        agent_name="customer_dissatisfaction",
        confidence=0.9,
        requires_clarification=False,
    )

    req = ConversationRequest(
        conversation_id="conv-break",
        agent_config=AgentConfig(id="a", name="Bot", persona="p", greeting="hi"),
        messages=[Message(role=MessageRole.USER, content="I'm really unhappy with this service")],
        current_intent_name="technical_support_request",
        selected_agent="technical_support",  # turn 2+: agent active when lock was established
    )

    with patch.object(
        orch._intent_router, "detect", new_callable=AsyncMock, return_value=high_conf_new
    ):
        with patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
        ):
            response = await orch.process_message(req)

    assert response.selected_intent == "customer_dissatisfaction_inquiry"
    assert response.selected_agent == "customer_dissatisfaction"


@pytest.mark.asyncio
async def test_intent_lock_held_on_low_confidence_new_intent() -> None:
    """Low-confidence classification does not break the lock even if the intent name differs."""
    from taskorbit.intent import _KNOWN_INTENTS

    orch = ConversationOrchestrator()
    locked_name = "technical_support_request"
    low_conf = _intent_result(
        name="general_inquiry",
        agent_name="general_inquiry",
        confidence=0.4,
        requires_clarification=True,
    )

    req = ConversationRequest(
        conversation_id="conv-hold",
        agent_config=AgentConfig(id="a", name="Bot", persona="p", greeting="hi"),
        messages=[Message(role=MessageRole.USER, content="one more thing about the error")],
        current_intent_name=locked_name,
        selected_agent="technical_support",  # turn 2+: agent active when lock was established
    )

    with patch.object(orch._intent_router, "detect", new_callable=AsyncMock, return_value=low_conf):
        with patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
        ):
            response = await orch.process_message(req)

    assert response.selected_intent == locked_name
    assert response.selected_agent == _KNOWN_INTENTS[locked_name].agent_name


@pytest.mark.asyncio
async def test_response_includes_locked_intent_name(mock_good_intent: Any) -> None:
    """After a successful turn the response carries locked_intent_name for the
    frontend to round-trip on the next request."""
    orch = ConversationOrchestrator()
    with patch.object(
        ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
    ):
        response = await orch.process_message(_make_request("I need tech support"))

    # The locked name must be a known intent (not empty/None) after a successful turn.
    assert response.locked_intent_name is not None
    assert response.locked_intent_name != ""


@pytest.mark.asyncio
async def test_no_intent_lock_when_current_intent_name_absent(mock_good_intent: Any) -> None:
    """With no current_intent_name the router runs normally (no lock path)."""
    orch = ConversationOrchestrator()
    with patch.object(
        orch._intent_router, "detect", new_callable=AsyncMock, return_value=mock_good_intent
    ) as mock_detect:
        with patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
        ):
            req = ConversationRequest(
                conversation_id="conv-nolock",
                agent_config=AgentConfig(id="a", name="Bot", persona="p", greeting="hi"),
                messages=[Message(role=MessageRole.USER, content="hello")],
                current_intent_name=None,
            )
            response = await orch.process_message(req)

    mock_detect.assert_called_once()
    assert response.selected_intent == mock_good_intent.name


# ---------------------------------------------------------------------------
# Manual transfer — UI-initiated handoff to a custom agent
# ---------------------------------------------------------------------------


def _fake_agent_record(agent_id: str = "abc123", name: str = "Custom Bot") -> Any:
    record = MagicMock()
    record.id = agent_id
    record.config = {"id": agent_id, "name": name, "persona": "Custom.", "greeting": "Hi!"}
    return record


@pytest.mark.asyncio
async def test_manual_transfer_succeeds(mock_good_intent: Any) -> None:
    from taskorbit.types import ManualTransferRequest

    orch = ConversationOrchestrator()
    req = ConversationRequest(
        conversation_id="conv-mt",
        agent_config=AgentConfig(id="original", name="Original", persona="p", greeting="hi"),
        messages=[Message(role=MessageRole.USER, content="transfer me")],
        manual_transfer=ManualTransferRequest(target_agent_id="abc123"),
    )
    with (
        patch(
            "taskorbit.database.crud.get_agent_configuration_by_id",
            new_callable=AsyncMock,
            return_value=_fake_agent_record(),
        ),
        patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
        ),
    ):
        response = await orch.process_message(req, db=AsyncMock())

    assert response.status != "error"


@pytest.mark.asyncio
async def test_manual_transfer_unknown_agent_returns_error() -> None:
    from taskorbit.types import ConversationStatus, ManualTransferRequest

    orch = ConversationOrchestrator()
    req = ConversationRequest(
        conversation_id="conv-mt-bad",
        agent_config=AgentConfig(id="original", name="Original", persona="p", greeting="hi"),
        messages=[Message(role=MessageRole.USER, content="transfer me")],
        manual_transfer=ManualTransferRequest(target_agent_id="does_not_exist"),
    )
    with patch(
        "taskorbit.database.crud.get_agent_configuration_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = await orch.process_message(req, db=AsyncMock())

    assert response.status == ConversationStatus.ERROR


@pytest.mark.asyncio
async def test_manual_transfer_no_db_returns_error() -> None:
    from taskorbit.types import ConversationStatus, ManualTransferRequest

    orch = ConversationOrchestrator()
    req = ConversationRequest(
        conversation_id="conv-mt-nodb",
        agent_config=AgentConfig(id="original", name="Original", persona="p", greeting="hi"),
        messages=[Message(role=MessageRole.USER, content="transfer me")],
        manual_transfer=ManualTransferRequest(target_agent_name="Some Agent"),
    )
    response = await orch.process_message(req, db=None)

    assert response.status == ConversationStatus.ERROR


@pytest.mark.asyncio
async def test_manual_transfer_clears_manual_transfer_on_retry(mock_good_intent: Any) -> None:
    from taskorbit.types import ManualTransferRequest

    orch = ConversationOrchestrator()
    req = ConversationRequest(
        conversation_id="conv-mt-clear",
        agent_config=AgentConfig(id="original", name="Original", persona="p", greeting="hi"),
        messages=[Message(role=MessageRole.USER, content="hi")],
        manual_transfer=ManualTransferRequest(target_agent_id="abc123"),
    )
    seen_requests: list[ConversationRequest] = []

    original = ConversationOrchestrator.process_message

    async def capture(
        self: Any, request: ConversationRequest, db: Any = None, **kwargs: Any
    ) -> Any:
        seen_requests.append(request)
        if request.manual_transfer is None:
            return ConversationResponse(
                conversation_id=request.conversation_id or "",
                reply=Message(role=MessageRole.ASSISTANT, content="ok"),
            )
        return await original(self, request, db, **kwargs)

    with (
        patch(
            "taskorbit.database.crud.get_agent_configuration_by_id",
            new_callable=AsyncMock,
            return_value=_fake_agent_record(),
        ),
        patch.object(ConversationOrchestrator, "process_message", capture),
    ):
        await orch.process_message(req, db=AsyncMock())

    # Second call must have manual_transfer cleared to avoid infinite recursion.
    assert seen_requests[-1].manual_transfer is None


@pytest.mark.asyncio
async def test_auto_transfer_to_custom_agent_via_process_message() -> None:
    """AgentTransferTool receives db+user_id through the real _dispatch_tool wiring.

    Drives process_message end-to-end (no _dispatch_tool mock) so the wiring is
    covered, not just the isolated tool. The mock DB returns a custom AgentConfiguration
    for the UUID target, proving that db and user_id reach _is_valid_target.
    """
    from unittest.mock import MagicMock

    from taskorbit.slots.models import SlotExtractionResult
    from taskorbit.types import ConfirmationConfig, ToolDefinition, ToolType

    custom_agent_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    fake_record = MagicMock()
    fake_record.id = custom_agent_id
    fake_record.name = "My Custom Agent"
    fake_record.config = {
        "id": custom_agent_id,
        "name": "My Custom Agent",
        "persona": "Custom persona",
        "greeting": "Hello from custom",
        "tools": [],
    }

    orch = ConversationOrchestrator()
    intent = _intent_result()
    transfer_tool = ToolDefinition(
        id="transfer-custom",
        name="agent_transfer",
        type=ToolType.AGENT_TRANSFER,
        description="transfer to custom",
        confirmation=ConfirmationConfig(required=False, prompt=""),
        parameters={"targets": [custom_agent_id]},
    )

    with (
        patch.object(orch._intent_router, "detect", new_callable=AsyncMock, return_value=intent),
        patch.object(ConversationOrchestrator, "_select_active_tool", return_value=transfer_tool),
        patch.object(
            ConversationOrchestrator,
            "_extract_slots",
            new_callable=AsyncMock,
            return_value=SlotExtractionResult(filled={}, missing=[]),
        ),
        patch.object(
            ConversationOrchestrator,
            "_call_llm",
            new_callable=AsyncMock,
            return_value="Transferring.",
        ),
        patch(
            "taskorbit.database.crud.get_agent_configuration_by_id",
            new_callable=AsyncMock,
            return_value=fake_record,
        ),
        # #224 dispatch-tracking hits db.execute() for real; an unconfigured
        # AsyncMock's .first() returns a truthy Mock, so without this the
        # transfer looks "already dispatched" and gets skipped. Not what this
        # test is exercising, so stub it out like the other orchestrator
        # internals patched above.
        patch.object(
            ConversationOrchestrator,
            "_tool_already_dispatched",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        mock_db = AsyncMock()
        response = await orch.process_message(
            _make_request("transfer me to my custom agent"),
            db=mock_db,
            user_id=42,
        )

    assert response.tool_invoked is not None
    assert response.tool_invoked.type == ToolType.AGENT_TRANSFER
    assert response.tool_invoked.parameters.get("targets", [None])[0] == custom_agent_id


@pytest.mark.asyncio
async def test_get_agent_config_by_id_cross_user_returns_none() -> None:
    """User A cannot retrieve an agent configuration owned by user B via by-id lookup."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from taskorbit.database.crud import get_agent_configuration_by_id
    from taskorbit.database.models import AgentConfiguration

    user_a_id = 1
    user_b_id = 2

    # DB returns a record owned by user B.
    user_b_record = MagicMock(spec=AgentConfiguration)
    user_b_record.id = "some-uuid"
    user_b_record.user_id = user_b_id

    mock_scalar = MagicMock()
    mock_scalar.scalar_one_or_none.return_value = None  # WHERE clause filters it out

    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(return_value=mock_scalar)

    # When user_id=user_a_id is passed, the WHERE clause scopes to user A.
    # The mock returns None (simulating that user B's record is excluded).
    result = await get_agent_configuration_by_id(mock_db, "some-uuid", user_id=user_a_id)
    assert result is None, "User A must not receive user B's agent configuration"


# ---------------------------------------------------------------------------
# LLM provider failures surface clearly (#197)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_error_during_intent_detection_returns_clear_message() -> None:
    """A provider failure in the intent router must yield a provider-error
    response, not the generic clarification reply that masked outages (#197)."""
    from taskorbit.integrations.llm.errors import LLMRateLimitError

    orch = ConversationOrchestrator()
    mock_metrics = MagicMock()

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        with patch.object(
            ConversationOrchestrator,
            "_call_llm_json",
            new_callable=AsyncMock,
            side_effect=LLMRateLimitError("OpenAI rate-limited: 429 insufficient_quota"),
        ):
            response = await orch.process_message(_make_request())

    assert response.status == "error"
    assert "language model provider" in response.reply.content
    assert "insufficient_quota" in response.error
    mock_metrics.conversation_errors_total.labels(
        error_type="llm_provider_error"
    ).inc.assert_called_once()


@pytest.mark.asyncio
async def test_provider_error_during_reply_generation_returns_clear_message(
    mock_good_intent: Any,
) -> None:
    from taskorbit.integrations.llm.errors import LLMAPIError

    orch = ConversationOrchestrator()
    mock_metrics = MagicMock()

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        with patch.object(
            ConversationOrchestrator,
            "_call_llm",
            new_callable=AsyncMock,
            side_effect=LLMAPIError("OpenAI API error: 500 server_error"),
        ):
            response = await orch.process_message(_make_request())

    assert response.status == "error"
    assert "language model provider" in response.reply.content
    mock_metrics.conversation_errors_total.labels(
        error_type="llm_provider_error"
    ).inc.assert_called_once()


@pytest.mark.asyncio
async def test_llm_timeout_error_maps_to_timeout_handler(mock_good_intent: Any) -> None:
    """LLMTimeoutError (provider-side timeout) must land in the llm_timeout
    bucket like the builtin TimeoutError, not in the generic runtime_error one."""
    from taskorbit.integrations.llm.errors import LLMTimeoutError

    orch = ConversationOrchestrator()
    mock_metrics = MagicMock()

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        with patch.object(
            ConversationOrchestrator,
            "_call_llm",
            new_callable=AsyncMock,
            side_effect=LLMTimeoutError("OpenAI request timed out"),
        ):
            response = await orch.process_message(_make_request())

    assert response.status == "error"
    assert "trouble connecting to my brain" in response.reply.content
    mock_metrics.conversation_errors_total.labels(error_type="llm_timeout").inc.assert_called_once()


@pytest.mark.asyncio
async def test_provider_error_in_stream_yields_error_response() -> None:
    from taskorbit.integrations.llm.errors import LLMAuthError

    orch = ConversationOrchestrator()
    mock_metrics = MagicMock()

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        with patch.object(
            ConversationOrchestrator,
            "_call_llm_json",
            new_callable=AsyncMock,
            side_effect=LLMAuthError("OpenAI authentication failed: 401"),
        ):
            events = []
            async for event in orch.process_message_stream(_make_request()):
                events.append(event)

    responses = [e for e in events if isinstance(e, ConversationResponse)]
    assert len(responses) == 1
    assert responses[0].status == "error"
    assert "language model provider" in responses[0].reply.content
    mock_metrics.conversation_errors_total.labels(
        error_type="llm_provider_error"
    ).inc.assert_called_once()


@pytest.mark.asyncio
async def test_slot_extraction_reraises_provider_errors() -> None:
    """_extract_slots must not convert a provider outage into 'all slots
    missing' — that would make the agent re-ask for data the user already gave."""
    from taskorbit.integrations.llm.errors import LLMRateLimitError

    orch = ConversationOrchestrator()
    request = _make_request("My email is user@example.com")

    with patch.object(
        ConversationOrchestrator,
        "_call_llm_json",
        new_callable=AsyncMock,
        side_effect=LLMRateLimitError("OpenAI rate-limited: 429"),
    ):
        with pytest.raises(LLMRateLimitError):
            await orch._extract_slots(
                request.messages,
                [{"name": "email", "type": "email", "required": True}],
                request.agent_config.llm,
            )


@pytest.mark.asyncio
async def test_llm_timeout_error_in_stream_maps_to_timeout_handler(
    mock_good_intent: Any,
) -> None:
    """The process_message_stream path must map LLMTimeoutError to the
    dedicated llm_timeout bucket and the connectivity-focused user message,
    not to the generic llm_provider_error bucket (#197). Mirrors the text-path
    test above."""
    from taskorbit.integrations.llm.errors import LLMTimeoutError

    orch = ConversationOrchestrator()
    mock_metrics = MagicMock()

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        with patch.object(
            ConversationOrchestrator,
            "_call_llm_json",
            new_callable=AsyncMock,
            side_effect=LLMTimeoutError("OpenAI request timed out"),
        ):
            events = []
            async for event in orch.process_message_stream(_make_request()):
                events.append(event)

    responses = [e for e in events if isinstance(e, ConversationResponse)]
    assert len(responses) == 1
    assert responses[0].status == "error"
    assert "trouble connecting to my brain" in responses[0].reply.content
    mock_metrics.conversation_errors_total.labels(error_type="llm_timeout").inc.assert_called_once()


@pytest.mark.asyncio
async def test_handler_ordering_llm_config_still_routes_to_llm_config_bucket(
    mock_good_intent: Any,
) -> None:
    """Regression guard for the #197 handler-order contract: LLMConfigError
    inherits from LLMError, so it MUST be caught by the LLMConfigError handler
    (label='llm_config'), not by the LLMError base handler (label='llm_provider_error').
    A future refactor that swaps the handler order would silently downgrade
    config errors, hiding onboarding problems ('did you set the API key?')
    behind the generic provider-error label."""
    from taskorbit.integrations.llm.errors import LLMConfigError

    orch = ConversationOrchestrator()
    mock_metrics = MagicMock()

    with patch("taskorbit.orchestration.get_metrics", return_value=mock_metrics):
        with patch.object(
            ConversationOrchestrator,
            "_call_llm_json",
            new_callable=AsyncMock,
            side_effect=LLMConfigError("OPENAI_API_KEY not set"),
        ):
            events = []
            async for event in orch.process_message_stream(_make_request()):
                events.append(event)

    responses = [e for e in events if isinstance(e, ConversationResponse)]
    assert len(responses) == 1
    assert responses[0].status == "error"
    assert "not properly configured" in responses[0].reply.content
    mock_metrics.conversation_errors_total.labels(error_type="llm_config").inc.assert_called_once()
    # And crucially, NOT the generic provider_error bucket.
    provider_error_calls = [
        c
        for c in mock_metrics.conversation_errors_total.labels.call_args_list
        if c.kwargs.get("error_type") == "llm_provider_error"
    ]
    assert not provider_error_calls, (
        "LLMConfigError leaked into the llm_provider_error bucket — check handler ordering "
        "in orchestration/__init__.py: LLMConfigError must be caught BEFORE LLMError base."
    )


# ---------------------------------------------------------------------------
# _select_active_tool — intent-driven transfer selection (#212)
# ---------------------------------------------------------------------------


class _FakeAgent:
    """Minimal stand-in exposing get_task_definitions like BaseAgent."""

    def __init__(self, tools):
        self._tools = tools

    def get_task_definitions(self):
        return self._tools


def _john_max_tools():
    from taskorbit.types import ConfirmationConfig, ToolDefinition, ToolType

    confirm = ConfirmationConfig(required=False, prompt="")
    return [
        ToolDefinition(
            id="collect_user_info",
            name="collect_user_info",
            type=ToolType.DATA_EXTRACTION,
            description="collect",
            confirmation=confirm,
            parameters={"params": []},
        ),
        ToolDefinition(
            id="end_call",
            name="end_call",
            type=ToolType.END_CALL,
            description="end",
            confirmation=confirm,
            parameters={},
        ),
        ToolDefinition(
            id="transfer_to_inquiry_agent",
            name="transfer_to_inquiry_agent",
            type=ToolType.AGENT_TRANSFER,
            description="hand off",
            confirmation=confirm,
            parameters={"targets": ["inquiry-agent"]},
        ),
    ]


def _intent_for(agent_name: str):
    from taskorbit.intent import IntentResult

    return IntentResult(name=agent_name or "unknown", description="", agent_name=agent_name)


def test_select_transfer_when_intent_routes_away() -> None:
    """#212: intent routing away + matching transfer tool selects the transfer,
    not tools[0], even though the target is the sloppy prod value."""
    orch = ConversationOrchestrator()
    tool = orch._select_active_tool(
        [],
        _FakeAgent(_john_max_tools()),
        intent=_intent_for("general_inquiry"),
        current_agent="demoday",
    )
    assert tool is not None
    assert tool.id == "transfer_to_inquiry_agent"


def test_select_pin_wins_over_transfer_rule() -> None:
    """A confirmation round-trip pin must still take precedence."""
    orch = ConversationOrchestrator()
    tool = orch._select_active_tool(
        [],
        _FakeAgent(_john_max_tools()),
        active_tool_id="collect_user_info",
        intent=_intent_for("general_inquiry"),
        current_agent="demoday",
    )
    assert tool is not None
    assert tool.id == "collect_user_info"


def test_select_stays_on_first_tool_when_intent_matches_current_agent() -> None:
    orch = ConversationOrchestrator()
    tool = orch._select_active_tool(
        [],
        _FakeAgent(_john_max_tools()),
        intent=_intent_for("general_inquiry"),
        current_agent="general_inquiry",
    )
    assert tool is not None
    assert tool.id == "collect_user_info"


def test_select_stays_on_first_tool_when_no_target_matches_destination() -> None:
    orch = ConversationOrchestrator()
    tool = orch._select_active_tool(
        [],
        _FakeAgent(_john_max_tools()),
        intent=_intent_for("sales"),
        current_agent="demoday",
    )
    assert tool is not None
    assert tool.id == "collect_user_info"


def test_select_stays_on_first_tool_for_unknown_intent() -> None:
    orch = ConversationOrchestrator()
    tool = orch._select_active_tool(
        [],
        _FakeAgent(_john_max_tools()),
        intent=_intent_for(""),
        current_agent="demoday",
    )
    assert tool is not None
    assert tool.id == "collect_user_info"


def test_select_unchanged_without_intent_argument() -> None:
    """Callers that never pass intent keep the legacy tools[0] behaviour."""
    orch = ConversationOrchestrator()
    tool = orch._select_active_tool([], _FakeAgent(_john_max_tools()))
    assert tool is not None
    assert tool.id == "collect_user_info"


def test_select_no_tools_returns_none_still() -> None:
    orch = ConversationOrchestrator()
    assert (
        orch._select_active_tool(
            [], _FakeAgent([]), intent=_intent_for("general_inquiry"), current_agent="x"
        )
        is None
    )


# ---------------------------------------------------------------------------
# tool_invoked carries the RESOLVED transfer target (#212)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transfer_tool_invoked_carries_canonical_target() -> None:
    """The response's tool_invoked must expose the canonical target, not the
    raw config string: the voice worker publishes parameters.targets[0] and
    the FE swap matches on it."""
    from unittest.mock import AsyncMock, patch

    from taskorbit.slots.models import SlotExtractionResult, SlotValue
    from taskorbit.types import ConfirmationConfig, ToolDefinition, ToolType

    orch = ConversationOrchestrator()
    intent = _intent_result(
        required_inputs=[{"name": "caller_name", "type": "string", "required": True}]
    )
    transfer_tool = ToolDefinition(
        id="transfer_to_inquiry_agent",
        name="transfer_to_inquiry_agent",
        type=ToolType.AGENT_TRANSFER,
        description="hand off",
        confirmation=ConfirmationConfig(required=False, prompt=""),
        parameters={"targets": ["inquiry-agent"]},
    )
    slot_result = SlotExtractionResult(
        filled={"caller_name": SlotValue(name="caller_name", value="Asad", slot_type="string")},
        missing=[],
    )

    with (
        patch.object(orch._intent_router, "detect", new_callable=AsyncMock, return_value=intent),
        patch.object(ConversationOrchestrator, "_select_active_tool", return_value=transfer_tool),
        patch.object(
            ConversationOrchestrator,
            "_extract_slots",
            new_callable=AsyncMock,
            return_value=slot_result,
        ),
        patch.object(
            ConversationOrchestrator,
            "_dispatch_tool",
            new_callable=AsyncMock,
            return_value=(
                {
                    "transferred_to": "general_inquiry",
                    "requested_target": "inquiry-agent",
                    "history_preserved": True,
                },
                0.0,
            ),
        ),
        patch.object(
            ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
        ),
    ):
        response = await orch.process_message(_make_request("transfer me"))

    assert response.tool_invoked is not None
    assert response.tool_invoked.type == ToolType.AGENT_TRANSFER
    assert response.tool_invoked.parameters["targets"] == ["general_inquiry"]


def test_select_no_refire_when_current_agent_is_template_slug() -> None:
    """After a completed voice handoff the worker reports the canonical
    template slug as the current agent; the transfer must NOT re-fire (#212)."""
    orch = ConversationOrchestrator()
    tool = orch._select_active_tool(
        [],
        _FakeAgent(_john_max_tools()),
        intent=_intent_for("general_inquiry"),
        current_agent="general-inquiry-agent",
    )
    assert tool is not None
    assert tool.id == "collect_user_info"


# ---------------------------------------------------------------------------
# #224 — a tool already dispatched must not be re-confirmed/re-dispatched
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session():
    """Fresh in-memory async database per test (mirrors test_crud.py)."""
    from taskorbit.database.models import Base

    engine = create_async_engine(_TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _dedup_test_request(decision: str | None = None, confirmation_id: str | None = None):
    from taskorbit.types import ConfirmationConfig, ToolDefinition, ToolType

    req = _make_request("save my info")
    req.agent_config.tools = [
        ToolDefinition(
            id="collect_user_info",
            name="collect_user_info",
            type=ToolType.DATA_EXTRACTION,
            description="Save",
            confirmation=ConfirmationConfig(required=True, prompt="Save it?"),
        )
    ]
    req.decision = decision
    req.confirmation_id = confirmation_id
    return req


class TestToolDispatchDeduplication:
    """#224: once a tool has actually dispatched in a conversation, later
    turns (e.g. after an intent flip re-selects the same tool, #227) must not
    re-ask for confirmation or re-dispatch it."""

    @pytest.mark.asyncio
    async def test_second_turn_does_not_redispatch_or_reconfirm(
        self, db_session: AsyncSession, mock_good_intent: Any
    ) -> None:
        from taskorbit.slots import SlotExtractionResult
        from taskorbit.types import ConversationStatus

        orch = ConversationOrchestrator()
        complete_slots = SlotExtractionResult(filled={"name": MagicMock(value="Alice")}, missing=[])
        mock_good_intent.required_inputs = [{"name": "name", "type": "string", "required": True}]

        with (
            patch.object(ConversationOrchestrator, "_call_llm", new_callable=AsyncMock) as mock_llm,
            patch.object(
                ConversationOrchestrator,
                "_extract_slots",
                new_callable=AsyncMock,
                return_value=complete_slots,
            ),
            patch.object(
                ConversationOrchestrator, "_dispatch_tool", new_callable=AsyncMock
            ) as mock_dispatch,
        ):
            mock_dispatch.return_value = ({"saved": True}, 0.0)
            mock_llm.return_value = "Saved!"

            # Turn 1: confirm and dispatch.
            turn1 = await orch.process_message(
                _dedup_test_request(decision="confirm", confirmation_id="collect_user_info"),
                db=db_session,
            )
            assert turn1.status == ConversationStatus.SUCCESS
            assert turn1.tool_invoked is not None
            mock_dispatch.assert_called_once()

            # Turn 2: same conversation, same complete slots, no decision this
            # time (mirrors an intent-flip re-selecting the same tool, #227) —
            # must NOT re-ask for confirmation or dispatch a second time.
            mock_llm.return_value = "Anything else?"
            turn2 = await orch.process_message(
                _dedup_test_request(decision=None, confirmation_id=None),
                db=db_session,
            )

        assert turn2.status != ConversationStatus.CONFIRMATION_REQUIRED
        assert turn2.tool_invoked is None
        mock_dispatch.assert_called_once()  # still just the one call from turn 1

    @pytest.mark.asyncio
    async def test_rejected_tool_can_still_be_asked_and_dispatched_later(
        self, db_session: AsyncSession, mock_good_intent: Any
    ) -> None:
        """A rejected confirmation must not be treated as 'already dispatched' —
        the user should be able to say yes on a later turn."""
        from taskorbit.slots import SlotExtractionResult
        from taskorbit.types import ConversationStatus

        orch = ConversationOrchestrator()
        complete_slots = SlotExtractionResult(filled={"name": MagicMock(value="Alice")}, missing=[])
        mock_good_intent.required_inputs = [{"name": "name", "type": "string", "required": True}]

        with (
            patch.object(
                ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
            ),
            patch.object(
                ConversationOrchestrator,
                "_extract_slots",
                new_callable=AsyncMock,
                return_value=complete_slots,
            ),
            patch.object(
                ConversationOrchestrator, "_dispatch_tool", new_callable=AsyncMock
            ) as mock_dispatch,
        ):
            mock_dispatch.return_value = ({"saved": True}, 0.0)

            # Turn 1: user rejects.
            turn1 = await orch.process_message(
                _dedup_test_request(decision="reject", confirmation_id="collect_user_info"),
                db=db_session,
            )
            assert turn1.status == ConversationStatus.REJECTED
            mock_dispatch.assert_not_called()

            # Turn 2: asked again (fresh turn, no decision) — must still ask,
            # since nothing has actually dispatched yet.
            turn2 = await orch.process_message(
                _dedup_test_request(decision=None, confirmation_id=None),
                db=db_session,
            )
            assert turn2.status == ConversationStatus.CONFIRMATION_REQUIRED

            # Turn 3: user confirms — dispatches for the first time.
            turn3 = await orch.process_message(
                _dedup_test_request(decision="confirm", confirmation_id="collect_user_info"),
                db=db_session,
            )

        assert turn3.status == ConversationStatus.SUCCESS
        assert turn3.tool_invoked is not None
        mock_dispatch.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_recorded_as_confirmed_in_tool_executions(
        self, db_session: AsyncSession, mock_good_intent: Any
    ) -> None:
        from taskorbit.database.crud import tool_already_dispatched
        from taskorbit.slots import SlotExtractionResult

        orch = ConversationOrchestrator()
        complete_slots = SlotExtractionResult(filled={"name": MagicMock(value="Alice")}, missing=[])
        mock_good_intent.required_inputs = [{"name": "name", "type": "string", "required": True}]

        with (
            patch.object(
                ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
            ),
            patch.object(
                ConversationOrchestrator,
                "_extract_slots",
                new_callable=AsyncMock,
                return_value=complete_slots,
            ),
            patch.object(
                ConversationOrchestrator,
                "_dispatch_tool",
                new_callable=AsyncMock,
                return_value=({"saved": True}, 0.0),
            ),
        ):
            await orch.process_message(
                _dedup_test_request(decision="confirm", confirmation_id="collect_user_info"),
                db=db_session,
            )

        assert await tool_already_dispatched(db_session, "conv-test", "collect_user_info") is True
        assert await tool_already_dispatched(db_session, "conv-test", "some-other-tool") is False

    @pytest.mark.asyncio
    async def test_without_db_behaves_as_before(self, mock_good_intent: Any) -> None:
        """Omitting db must not change behaviour — dedup tracking is opt-in."""
        from taskorbit.slots import SlotExtractionResult

        orch = ConversationOrchestrator()
        complete_slots = SlotExtractionResult(filled={"name": MagicMock(value="Alice")}, missing=[])
        mock_good_intent.required_inputs = [{"name": "name", "type": "string", "required": True}]

        with (
            patch.object(
                ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="ok"
            ),
            patch.object(
                ConversationOrchestrator,
                "_extract_slots",
                new_callable=AsyncMock,
                return_value=complete_slots,
            ),
            patch.object(
                ConversationOrchestrator,
                "_dispatch_tool",
                new_callable=AsyncMock,
                return_value=({"saved": True}, 0.0),
            ) as mock_dispatch,
        ):
            turn1 = await orch.process_message(
                _dedup_test_request(decision="confirm", confirmation_id="collect_user_info")
            )
            turn2 = await orch.process_message(
                _dedup_test_request(decision="confirm", confirmation_id="collect_user_info")
            )

        assert turn1.tool_invoked is not None
        assert turn2.tool_invoked is not None
        assert mock_dispatch.call_count == 2

    @pytest.mark.asyncio
    async def test_end_call_shortcut_does_not_reask_after_dispatch(
        self, db_session: AsyncSession
    ) -> None:
        """The user-initiated end-call shortcut bypasses _run_dispatch_step
        entirely, so it needs its own dedup guard (#224) — a stray re-entry
        into the shortcut (e.g. the user saying goodbye again, or a decision
        round-trip glitch) must not re-ask/re-dispatch end_call."""
        from taskorbit.types import ConfirmationConfig, ConversationStatus, ToolDefinition, ToolType

        orch = ConversationOrchestrator()
        end_call_tool = ToolDefinition(
            id="end-1",
            name="end_call",
            type=ToolType.END_CALL,
            description="End the call",
            confirmation=ConfirmationConfig(required=True, prompt=""),
        )

        def _req(content: str, decision: str | None = None, confirmation_id: str | None = None):
            req = ConversationRequest(
                conversation_id="conv-end-dedup",
                agent_config=AgentConfig(
                    id="agent-1",
                    name="Bot",
                    persona="Helpful bot",
                    greeting="Hi!",
                    tools=[end_call_tool],
                ),
                messages=[Message(role=MessageRole.USER, content=content)],
            )
            req.decision = decision
            req.confirmation_id = confirmation_id
            return req

        with (
            patch.object(
                ConversationOrchestrator, "_call_llm", new_callable=AsyncMock, return_value="Bye!"
            ),
            patch.object(
                ConversationOrchestrator,
                "_dispatch_tool",
                new_callable=AsyncMock,
                return_value=({}, 0.0),
            ) as mock_dispatch,
        ):
            turn1 = await orch.process_message(_req("goodbye"), db=db_session)
            assert turn1.status == ConversationStatus.CONFIRMATION_REQUIRED

            turn2 = await orch.process_message(
                _req("yes", decision="confirm", confirmation_id="end-1"), db=db_session
            )
            assert turn2.status == ConversationStatus.ENDED
            mock_dispatch.assert_called_once()

            # Stray re-entry: user says goodbye again (or the shortcut is
            # re-entered some other way) after end_call already dispatched.
            turn3 = await orch.process_message(_req("goodbye"), db=db_session)

        assert turn3.status != ConversationStatus.CONFIRMATION_REQUIRED
        assert turn3.tool_invoked is None
        mock_dispatch.assert_called_once()  # still just the one call from turn 2
