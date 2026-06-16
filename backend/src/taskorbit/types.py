"""Shared Pydantic models for the TaskOrbit backend.

This module is the single source of truth for all data structures exchanged
between the API layer, orchestration engine, agents, tools, and the frontend.
It mirrors the AgentConfig TypeScript schema in frontend/src/types/agentConfig.ts.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ToolType(str, Enum):
    DATA_EXTRACTION = "data_extraction"
    AGENT_TRANSFER = "agent_transfer"
    END_CALL = "end_call"
    EXTERNAL_API = "external_api"


class ConversationStatus(str, Enum):
    SUCCESS = "success"
    CLARIFICATION = "clarification"
    CONFIRMATION_REQUIRED = "confirmation_required"
    WORKFLOW_CONFIRMATION_REQUIRED = "workflow_confirmation_required"
    HANDOFF_BLOCKED = "handoff_blocked"
    REJECTED = "rejected"
    ENDED = "ended"
    ERROR = "error"


class STTProvider(str, Enum):
    """Speech-to-text providers. Both entries support STT and TTS (#135),
    so either can be selected independently of the TTS choice."""

    DEEPGRAM = "deepgram"
    ELEVENLABS = "elevenlabs"


class LLMProvider(str, Enum):
    OPENAI = "openai"
    GOOGLE = "google"


class TTSProvider(str, Enum):
    """Text-to-speech providers. Mirror of STTProvider: both vendors are
    dual-capability, enabling the full interchangeable matrix (#135)."""

    ELEVENLABS = "elevenlabs"
    DEEPGRAM = "deepgram"


# ---------------------------------------------------------------------------
# Conversation primitives
# ---------------------------------------------------------------------------


class Message(BaseModel):
    role: MessageRole
    content: str
    timestamp: datetime | None = None


# ---------------------------------------------------------------------------
# Agent configuration (mirrors frontend AgentConfig schema)
# ---------------------------------------------------------------------------


class ConfirmationConfig(BaseModel):
    required: bool = False
    prompt: str = ""


class ToolDefinition(BaseModel):
    id: str
    name: str
    type: ToolType
    description: str = ""
    confirmation: ConfirmationConfig = Field(default_factory=ConfirmationConfig)
    parameters: dict[str, Any] = Field(default_factory=dict)


class STTConfig(BaseModel):
    provider: STTProvider = STTProvider.DEEPGRAM
    language: str = "multi"
    model: str = "nova-3"


class LLMConfig(BaseModel):
    provider: LLMProvider = LLMProvider.OPENAI
    model: str = "gpt-4o-mini"


class TTSConfig(BaseModel):
    provider: TTSProvider = TTSProvider.ELEVENLABS
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    model: str = "eleven_multilingual_v2"


class PersonaConstraints(BaseModel):
    """Optional persona scope, out-of-scope domains, and refusal template.

    Augments the system prompt so the LLM stays in role on off-topic input
    (ticket #69). All fields are optional — a constraints object with no
    fields populated is treated as a no-op by ``with_persona_guardrails``.
    """

    scope: str | None = None
    out_of_scope: list[str] = Field(default_factory=list)
    refusal_template: str | None = None


class ContextLimitConfig(BaseModel):
    """Configuration for conversation history limits and truncation.

    Controls how many messages the agent remembers before the oldest are
    automatically removed (FIFO). The system prompt is always protected and
    never truncated.

    Only ``"message_count"`` is supported in this sprint. Token-threshold
    truncation and summarisation are tracked as follow-up work — see the
    "Context-limit follow-up" issue.

    Example:
        Keep the last 50 messages:
        ContextLimitConfig(type="message_count", value=50)
    """

    type: Literal["message_count"] = Field(
        default="message_count",
        description='Truncation strategy. Only "message_count" is enforced today.',
    )
    value: int = Field(
        default=50,
        ge=2,
        le=499,
        description="Maximum non-system messages to retain (2-499).",
    )


class AgentConfig(BaseModel):
    id: str
    name: str
    persona: str
    greeting: str
    stt: STTConfig = Field(default_factory=STTConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    tools: list[ToolDefinition] = Field(default_factory=list)
    persona_constraints: PersonaConstraints | None = None
    context_limit: ContextLimitConfig | None = None
    workflow_dependencies: list[str] = Field(default_factory=list)
    allowed_handoffs: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API request / response shapes
# ---------------------------------------------------------------------------


class ConfirmationResponsePayload(BaseModel):
    confirmation_id: str
    action: str
    description: str


class ManualTransferRequest(BaseModel):
    """Carries a UI-initiated agent transfer directive.

    Either ``target_agent_id`` (UUID hex of a saved AgentConfiguration) or
    ``target_agent_name`` (human-readable name) must be set. When both are
    provided, ``target_agent_id`` takes precedence.
    """

    target_agent_id: str | None = None
    target_agent_name: str | None = None

    @model_validator(mode="after")
    def require_at_least_one_target(self) -> ManualTransferRequest:
        if not (self.target_agent_id or self.target_agent_name):
            raise ValueError(
                "ManualTransferRequest requires at least one of target_agent_id or target_agent_name"
            )
        return self


class ConversationRequest(BaseModel):
    conversation_id: str | None = None  # omit on first message; backend assigns and returns one
    agent_config: AgentConfig
    messages: list[Message]
    current_intent_name: str | None = None
    selected_agent: str | None = None
    active_tool_id: str | None = None
    # AC #49: Decision fields
    confirmation_id: str | None = None
    decision: Literal["confirm", "reject"] | None = None
    # #71: Workflow state
    completed_workflow_steps: list[str] = Field(default_factory=list)
    # AC #71: Map of agent IDs to their full configurations for resolving dependencies.
    dependency_configs: dict[str, AgentConfig] = Field(default_factory=dict)
    # Manual transfer: UI-initiated handoff to a specific agent (bypasses intent detection)
    manual_transfer: ManualTransferRequest | None = None


class ConversationResponse(BaseModel):
    conversation_id: str
    reply: Message
    tool_invoked: ToolDefinition | None = None
    # AC #49: Detailed confirmation payload
    confirmation: ConfirmationResponsePayload | None = None
    selected_intent: str = ""
    selected_agent: str = ""
    intent_confidence: float = 0.0
    status: ConversationStatus = ConversationStatus.SUCCESS
    error: str = ""
    extracted_slots: dict[str, Any] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    locked_intent_name: str | None = None
    next_active_tool_id: str | None = None
    # #71: Workflow state
    completed_workflow_steps: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LiveKit token endpoint
# ---------------------------------------------------------------------------


class LiveKitTokenRequest(BaseModel):
    identity: str = Field(..., min_length=1, max_length=128)
    room: str = Field(..., min_length=1, max_length=128)
    # Optional structured payload the frontend may attach to the JWT.
    # The LiveKit voice worker reads this back as participant metadata
    # to customise its persona, greeting, and (later) tools per-call.
    # Capped at a few KB to avoid bloating the JWT.
    metadata: dict[str, Any] | None = Field(default=None)
    # LiveKit Cloud agent dispatch name (often ``CA_...``). Overrides
    # ``LIVEKIT_AGENT_DISPATCH_NAME`` from the environment when set.
    agent_dispatch_name: str | None = Field(default=None, max_length=256)


class LiveKitTokenResponse(BaseModel):
    token: str
    url: str
    room: str
    identity: str


# ---------------------------------------------------------------------------
# Agent-configuration persistence request / response shapes
# ---------------------------------------------------------------------------


class AgentConfigurationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_at: datetime
    updated_at: datetime | None = None


class AgentConfigurationDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    # Stored as opaque JSON so the full FE contract (Preet's reference shape,
    # which is wider than the orchestrator's narrow AgentConfig wire type)
    # round-trips intact through save → load. The orchestrator path uses its
    # own narrower AgentConfig + an FE-side adapter (conversationApi.ts).
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None = None


class AgentConfigurationCreate(BaseModel):
    """Request body for POST /v1/agent-configs."""

    name: str = Field(..., min_length=1, max_length=200)
    config: dict[str, Any]


class AgentConfigurationUpdate(BaseModel):
    """Request body for PUT /v1/agent-configs/{id}."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, Any] | None = None
