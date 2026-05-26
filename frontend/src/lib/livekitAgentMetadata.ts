/**
 * Maps the UI `AgentConfig` into the JSON shape the voice worker expects on
 * the LiveKit JWT (`POST /v1/livekit/token` → `metadata`), which must match
 * the backend `AgentConfig` Pydantic model (id, name, persona, greeting, …).
 */

import type { AgentConfig } from "@/types/agentConfig";

export function buildLiveKitWorkerMetadata(
  agent: AgentConfig,
  conversationId: string,
): Record<string, unknown> {
  const llmProvider = agent.llm.provider === "gemini" ? "google" : "openai";
  return {
    id: agent.agent_id,
    name: agent.name,
    persona: agent.instructions,
    greeting: agent.first_message.message,
    conversation_id: conversationId,
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
  };
}