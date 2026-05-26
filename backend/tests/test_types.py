"""Tests for shared Pydantic models in taskorbit.types."""

from __future__ import annotations

from taskorbit.types import (
    AgentConfig,
    ConfirmationConfig,
    ConversationRequest,
    ConversationResponse,
    LLMConfig,
    Message,
    MessageRole,
    PersonaConstraints,
    STTConfig,
    ToolDefinition,
    ToolType,
    TTSConfig,
)


def _make_tool(tool_type: ToolType = ToolType.DATA_EXTRACTION) -> ToolDefinition:
    return ToolDefinition(
        id="tool-1",
        name="Collect Info",
        type=tool_type,
        description="Collect user information",
        confirmation=ConfirmationConfig(required=True, prompt="Shall I save this?"),
    )


def _make_agent_config() -> AgentConfig:
    return AgentConfig(
        id="agent-1",
        name="Support Bot",
        persona="Friendly support agent",
        greeting="Hi! How can I help?",
    )


def test_message_role_enum() -> None:
    # Use .value for comparisons to satisfy mypy's strict type checking
    # when comparing Enum members to raw strings.
    assert MessageRole.USER.value == "user"
    assert MessageRole.ASSISTANT.value == "assistant"
    assert MessageRole.SYSTEM.value == "system"


def test_tool_type_enum() -> None:
    # Use .value for comparisons to satisfy mypy's strict type checking
    # when comparing Enum members to raw strings.
    assert ToolType.DATA_EXTRACTION.value == "data_extraction"
    assert ToolType.AGENT_TRANSFER.value == "agent_transfer"
    assert ToolType.END_CALL.value == "end_call"


def test_message_defaults() -> None:
    msg = Message(role=MessageRole.USER, content="Hello")
    assert msg.role == MessageRole.USER
    assert msg.content == "Hello"
    assert msg.timestamp is None


def test_tool_definition_instantiation() -> None:
    tool = _make_tool()
    assert tool.id == "tool-1"
    assert tool.type == ToolType.DATA_EXTRACTION
    assert tool.confirmation.required is True
    assert tool.parameters == {}


def test_agent_config_defaults() -> None:
    config = _make_agent_config()
    assert config.stt == STTConfig()
    assert config.llm == LLMConfig()
    assert config.tts == TTSConfig()
    assert config.tools == []


def test_agent_config_with_tools() -> None:
    config = AgentConfig(
        id="agent-2",
        name="Sales Bot",
        persona="Sales agent",
        greeting="Hello!",
        tools=[_make_tool(ToolType.END_CALL)],
    )
    assert len(config.tools) == 1
    assert config.tools[0].type == ToolType.END_CALL


def test_conversation_request_instantiation() -> None:
    req = ConversationRequest(
        conversation_id="conv-123",
        agent_config=_make_agent_config(),
        messages=[Message(role=MessageRole.USER, content="Hi")],
    )
    assert req.conversation_id == "conv-123"
    assert len(req.messages) == 1


def test_conversation_response_defaults() -> None:
    resp = ConversationResponse(
        conversation_id="conv-123",
        reply=Message(role=MessageRole.ASSISTANT, content="Hello!"),
    )
    assert resp.tool_invoked is None
    assert resp.requires_confirmation is False
    assert resp.confirmation_prompt == ""


# ---------------------------------------------------------------------------
# PersonaConstraints + AgentConfig.persona_constraints (ticket #69)
# ---------------------------------------------------------------------------


def test_persona_constraints_all_fields_optional() -> None:
    """PersonaConstraints can be instantiated with zero arguments."""
    pc = PersonaConstraints()
    assert pc.scope is None
    assert pc.out_of_scope == []
    assert pc.refusal_template is None


def test_persona_constraints_populated() -> None:
    pc = PersonaConstraints(
        scope="TechStore support.",
        out_of_scope=["therapy", "legal advice"],
        refusal_template="I can only help with TechStore.",
    )
    assert pc.scope == "TechStore support."
    assert pc.out_of_scope == ["therapy", "legal advice"]
    assert pc.refusal_template == "I can only help with TechStore."


def test_agent_config_persona_constraints_defaults_to_none() -> None:
    """Backward-compatibility — existing AgentConfig calls work unchanged."""
    config = _make_agent_config()
    assert config.persona_constraints is None


def test_agent_config_round_trips_persona_constraints() -> None:
    """model_dump → model_validate preserves persona_constraints byte-for-byte."""
    original = AgentConfig(
        id="agent-1",
        name="John",
        persona="TechStore support.",
        greeting="Hi!",
        persona_constraints=PersonaConstraints(
            scope="TechStore.",
            out_of_scope=["therapy"],
            refusal_template="Sorry.",
        ),
    )
    dumped = original.model_dump()
    restored = AgentConfig.model_validate(dumped)
    assert restored.persona_constraints == original.persona_constraints
