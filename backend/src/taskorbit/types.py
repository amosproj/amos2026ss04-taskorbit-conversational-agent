"""Shared Pydantic models for the TaskOrbit backend.

This module is the single source of truth for all data structures exchanged
between the API layer, orchestration engine, agents, tools, and the frontend.
It mirrors the AgentConfig TypeScript schema in frontend/src/types/agentConfig.ts.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

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


class STTProvider(str, Enum):
    DEEPGRAM = "deepgram"


class LLMProvider(str, Enum):
    OPENAI = "openai"
    GOOGLE = "google"


class TTSProvider(str, Enum):
    ELEVENLABS = "elevenlabs"


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
    required: bool = True
    prompt: str = ""


class ToolDefinition(BaseModel):
    id: str
    name: str
    type: ToolType
    description: str
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


class AgentConfig(BaseModel):
    id: str
    name: str
    persona: str
    greeting: str
    stt: STTConfig = Field(default_factory=STTConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    tools: list[ToolDefinition] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API request / response shapes
# ---------------------------------------------------------------------------


class ConversationRequest(BaseModel):
    conversation_id: str
    agent_config: AgentConfig
    messages: list[Message]


class ConversationResponse(BaseModel):
    conversation_id: str
    reply: Message
    tool_invoked: ToolDefinition | None = None
    requires_confirmation: bool = False 
    confirmation_prompt: str = "" #e.g. "I'll save your contact info. OK?" 


# ---------------------------------------------------------------------------
# LiveKit token endpoint
# ---------------------------------------------------------------------------


class LiveKitTokenRequest(BaseModel):
    room_name: str
    participant_name: str


class LiveKitTokenResponse(BaseModel):
    token: str
    url: str
