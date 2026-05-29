/**
 * Thin client for GET/PUT/DELETE /api/v1/user-agents.
 *
 * Handles the shape mismatch between the backend AgentConfig JSON
 * (persona, greeting, id) and the frontend AgentConfig type
 * (instructions, first_message, agent_id).
 */

import type { AgentConfig } from "@/types/agentConfig";

// ---------------------------------------------------------------------------
// Wire types (backend shape)
// ---------------------------------------------------------------------------

export type UserAgentEntry = {
  id: string;
  template_id: string | null;
  name: string;
  config: BackendAgentConfig;
  is_default: boolean;
  is_customized: boolean;
};

type BackendAgentConfig = {
  id: string;
  name: string;
  persona: string;
  greeting: string;
  stt: { provider: string; language?: string; model: string };
  llm: { provider: string; model: string };
  tts: { provider: string; voice_id: string; model: string };
  tools: unknown[];
  persona_constraints?: {
    scope?: string;
    out_of_scope?: string[];
    refusal_template?: string;
  } | null;
};

// ---------------------------------------------------------------------------
// Adapters
// ---------------------------------------------------------------------------

export function backendToFrontendAgent(entry: UserAgentEntry): AgentConfig {
  const c = entry.config;
  return {
    agent_id: c.id,
    name: c.name,
    instructions: c.persona,
    first_message: { type: "text", message: c.greeting, prompt: "" },
    stt: { provider: c.stt.provider as "deepgram", model: c.stt.model },
    llm: { provider: (c.llm.provider ?? "openai") as "openai" | "gemini", model: c.llm.model },
    tts: { provider: c.tts.provider as "elevenlabs", voice_id: c.tts.voice_id, model: c.tts.model },
    tools: [],
    variables: {},
    engine: {},
    persona_constraints: c.persona_constraints ?? undefined,
  };
}

function frontendToBackendConfig(agent: AgentConfig): BackendAgentConfig {
  return {
    id: agent.agent_id,
    name: agent.name,
    persona: agent.instructions,
    greeting: agent.first_message.message,
    stt: { provider: agent.stt.provider, language: "multi", model: agent.stt.model },
    llm: { provider: agent.llm.provider, model: agent.llm.model },
    tts: { provider: agent.tts.provider, voice_id: agent.tts.voice_id, model: agent.tts.model },
    tools: [],
    persona_constraints: agent.persona_constraints ?? null,
  };
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export async function fetchUserAgents(signal?: AbortSignal): Promise<UserAgentEntry[]> {
  const res = await fetch("/api/v1/user-agents", { signal });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }
  return res.json() as Promise<UserAgentEntry[]>;
}

export async function customizeUserAgent(
  agentId: string,
  agent: AgentConfig,
): Promise<UserAgentEntry> {
  const body = {
    name: agent.name,
    config: frontendToBackendConfig(agent),
  };
  const res = await fetch(`/api/v1/user-agents/${encodeURIComponent(agentId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }
  return res.json() as Promise<UserAgentEntry>;
}

export async function deleteUserAgent(agentId: string): Promise<void> {
  const res = await fetch(`/api/v1/user-agents/${encodeURIComponent(agentId)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }
}
