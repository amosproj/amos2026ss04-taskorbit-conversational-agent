/**
 * Maps the UI `AgentConfig` into the JSON shape the voice worker expects on
 * the LiveKit JWT (`POST /v1/livekit/token` → `metadata`), which must match
 * the backend `AgentConfig` Pydantic model (id, name, persona, greeting, …).
 *
 * Tool definitions are omitted for now — the echo orchestrator ignores them
 * and serialising Meisterwerk tools into backend ToolDefinition rows is a
 * separate ticket.
 *
 * `persona_constraints` is included so #69 guardrails apply to the voice
 * path too; before #100 the worker discarded the whole metadata and used
 * a hardcoded default agent, so guardrails never reached voice sessions.
 */

import type { AgentConfig } from "@/types/agentConfig";

export function buildLiveKitWorkerMetadata(agent: AgentConfig): Record<string, unknown> {
  const llmProvider = agent.llm.provider === "gemini" ? "google" : "openai";
  return {
    id: agent.agent_id,
    name: agent.name,
    persona: agent.instructions,
    greeting: agent.first_message.message,
    stt: {
      provider: "deepgram",
      language: "multi",
      model: agent.stt.model,
    },
    llm: {
      provider: llmProvider,
      model: agent.llm.model,
    },
    tts: {
      provider: "elevenlabs",
      voice_id: agent.tts.voice_id,
      model: agent.tts.model,
    },
    tools: [],
    persona_constraints: agent.persona_constraints ?? null,
  };
}
