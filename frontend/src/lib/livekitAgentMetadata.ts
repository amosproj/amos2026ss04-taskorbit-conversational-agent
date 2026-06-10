/**
 * Maps the UI `AgentConfig` into the JSON shape the voice worker expects on
 * the LiveKit JWT (`POST /v1/livekit/token` -> `metadata`), which must match
 * the backend `AgentConfig` Pydantic model (id, name, persona, greeting, ...).
 *
 * `persona_constraints` is included so #69 guardrails apply to the voice
 * path too; before #100 the worker discarded the whole metadata and used
 * a hardcoded default agent, so guardrails never reached voice sessions.
 *
 * Tools are serialised into the backend `ToolDefinition` wire shape (same
 * adapter used by conversationApi.ts) so the voice path's orchestrator can
 * dispatch agent_transfer / data_extraction the same way the text path does.
 * AC7 of #8, voice handoff continuity.
 */

import {
  END_CALL_DEFAULT_DESCRIPTION,
  type AgentConfig,
  type ConfirmationsConfig,
  type ToolDefinition as FrontendTool,
} from "@/types/agentConfig";

type BackendTool = {
  id: string;
  name: string;
  type: string;
  description: string;
  confirmation: { required: boolean; prompt: string };
  parameters: Record<string, unknown>;
};

function toolNeedsConfirmation(
  toolName: string,
  confirmations: ConfirmationsConfig | undefined,
): boolean {
  if (confirmations === undefined) return false; // missing means legacy/disabled
  if (!confirmations.required) return false;
  return confirmations.tools.length === 0 || confirmations.tools.includes(toolName);
}

function adaptTool(
  tool: FrontendTool,
  confirmations: ConfirmationsConfig | undefined,
): BackendTool {
  const base = {
    id: tool.name || tool.type,
    name: tool.name,
    type: tool.type,
    description:
      tool.description?.trim() || (tool.type === "end_call" ? END_CALL_DEFAULT_DESCRIPTION : ""),
    confirmation: { required: toolNeedsConfirmation(tool.name, confirmations), prompt: "" },
  };
  if (tool.type === "data_extraction") {
    return { ...base, parameters: { params: tool.params } };
  }
  if (tool.type === "agent_transfer") {
    return { ...base, parameters: { targets: tool.targets } };
  }
  return { ...base, parameters: {} };
}

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
    tools: agent.tools.map((t) => adaptTool(t, agent.confirmations)),
    persona_constraints: agent.persona_constraints ?? null,
  };
}
