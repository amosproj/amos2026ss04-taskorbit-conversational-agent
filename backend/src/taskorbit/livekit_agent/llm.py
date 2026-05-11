"""Custom LLM bridge — adapts ConversationOrchestrator to AgentSession.

Rather than implementing the full ``livekit.agents.llm.LLM`` provider
interface (which expects streaming chat completions, function-call
parsing, usage stats, etc.), we override the much smaller ``llm_node``
hook on ``Agent``. The hook is the single point ``AgentSession`` uses to
generate assistant replies, so customising it is the cleanest way to
plug a non-LLM backend (or a future real LLM) into the voice pipeline.

The orchestrator stays the source of truth for "what should the
assistant say next?". Today it's an echo stub; swapping in a real LLM
later only requires changing ``ConversationOrchestrator.process_message``
— this adapter does not need to change.
"""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Any

from livekit.agents import Agent, FunctionTool, ModelSettings, llm

from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.types import (
    AgentConfig,
    ConversationRequest,
    LLMConfig,
    Message,
    MessageRole,
    STTConfig,
    TTSConfig,
)


def _default_agent_config() -> AgentConfig:
    """Minimal AgentConfig used when no agent metadata is attached.

    The voice worker doesn't have access to the frontend agent config
    today (token metadata wiring is a future task). For now we synthesise
    a plain config so the orchestrator can still produce a reply.
    """
    return AgentConfig(
        id="livekit-default",
        name="TaskOrbit",
        persona="A helpful voice assistant.",
        greeting="Hello!",
        stt=STTConfig(),
        llm=LLMConfig(),
        tts=TTSConfig(),
        tools=[],
    )


def _convert_chat_ctx_to_messages(chat_ctx: llm.ChatContext) -> list[Message]:
    """Translate AgentSession's ChatContext into the orchestrator's Message list.

    Only user/assistant/system entries with plain text content are kept —
    function-call items are ignored because the orchestrator is text-only.
    """
    messages: list[Message] = []
    for item in chat_ctx.items:
        role = getattr(item, "role", None)
        if role not in ("user", "assistant", "system"):
            continue
        text = _extract_text(item)
        if not text:
            continue
        try:
            messages.append(
                Message(role=MessageRole(role), content=text),
            )
        except ValueError:
            continue
    return messages


def _extract_text(item: Any) -> str:
    """Best-effort plain-text extractor for ChatMessage-like items.

    ``content`` is typically ``str | list[str | ImageContent | AudioContent]``;
    we keep only the string parts and join them.
    """
    content = getattr(item, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for entry in content:
            if isinstance(entry, str):
                parts.append(entry)
        return " ".join(parts).strip()
    text_attr = getattr(item, "text_content", None)
    if isinstance(text_attr, str):
        return text_attr.strip()
    return ""


class OrchestratorAgent(Agent):
    """``Agent`` subclass that routes LLM inference through ConversationOrchestrator.

    AgentSession will call ``llm_node`` once per user turn with the full
    chat context. We translate that context into a ``ConversationRequest``,
    hand it to the orchestrator, and yield the assistant reply as a single
    ``ChatChunk``. Streaming is left for a real LLM integration; the
    pipeline can stream this single chunk into the TTS without issue.

    Push-to-talk guard: ``llm_node`` only processes when ``request_reply()``
    has been called first. Preemptive generation calls from AgentSession
    are silently dropped, preventing double responses.
    """

    def __init__(
        self,
        orchestrator: ConversationOrchestrator,
        *,
        instructions: str | None = None,
        agent_config: AgentConfig | None = None,
        conversation_id: str = "livekit-session",
    ) -> None:
        super().__init__(
            instructions=instructions or "You are TaskOrbit, a helpful voice assistant.",
        )
        self._orchestrator = orchestrator
        self._agent_config = agent_config or _default_agent_config()
        self._conversation_id = conversation_id
        self._reply_requested: bool = False

    def request_reply(self) -> None:
        """Signal that the next ``llm_node`` call should actually produce a reply.

        Call this immediately before ``session.generate_reply()`` from the
        data channel handler. Without it, ``llm_node`` returns empty so that
        AgentSession's preemptive generation does not produce a spurious response.
        """
        self._reply_requested = True

    async def llm_node(  # type: ignore[override]
        self,
        chat_ctx: llm.ChatContext,
        tools: list[FunctionTool],  # type: ignore[type-arg]
        model_settings: ModelSettings,
    ) -> AsyncIterable[llm.ChatChunk | str]:
        """Generate the assistant reply for the current turn.

        We ignore ``tools`` and ``model_settings`` here: the orchestrator
        owns its own tool dispatch and the response is plain text. If a
        real LLM is wired in later, this method should change to delegate
        back to ``Agent.default.llm_node`` instead.
        """
        if not self._reply_requested:
            # Preemptive generation call — not triggered by Send. Drop it.
            return
        self._reply_requested = False

        messages = _convert_chat_ctx_to_messages(chat_ctx)
        last_user = next((m for m in reversed(messages) if m.role == MessageRole.USER), None)
        if last_user:
            print(f"[STT] {last_user.content}", flush=True)
        request = ConversationRequest(
            conversation_id=self._conversation_id,
            agent_config=self._agent_config,
            messages=messages,
        )
        response = await self._orchestrator.process_message(request)
        text = response.reply.content or ""
        if not text:
            return
        yield text
