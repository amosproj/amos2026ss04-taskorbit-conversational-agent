/**
 * Thin client for POST /api/v1/conversations/process.
 *
 * Maps the frontend AgentConfig schema (Preet's contract) to the shape
 * the Python backend expects, sends the request through the Vite proxy,
 * and returns the assistant reply text.
 *
 * The Vite proxy rewrites /api/* → /* on localhost:8000, so this works
 * in dev without CORS configuration.
 */

import type { AgentConfig, ToolDefinition as FrontendTool } from "@/types/agentConfig";
import type { LiveTranscriptTurn } from "@/types/callState";

// ---------------------------------------------------------------------------
// Backend wire shapes (mirrors backend/src/taskorbit/types.py)
// ---------------------------------------------------------------------------

type BackendTool = {
  id: string;
  name: string;
  type: string;
  description: string;
  confirmation: { required: boolean; prompt: string };
  parameters: Record<string, unknown>;
};

type BackendPersonaConstraints = {
  scope?: string;
  out_of_scope?: string[];
  refusal_template?: string;
};

type BackendContextLimit = {
  type: "message_count";
  value: number;
};

type BackendAgentConfig = {
  id: string;
  name: string;
  persona: string;
  greeting: string;
  stt: { provider: string; language: string; model: string };
  llm: { provider: string; model: string };
  tts: { provider: string; voice_id: string; model: string };
  tools: BackendTool[];
  persona_constraints?: BackendPersonaConstraints;
  context_limit?: BackendContextLimit;
};

type BackendMessage = { role: "user" | "assistant" | "system"; content: string };

type ConversationRequest = {
  conversation_id: string;
  agent_config: BackendAgentConfig;
  messages: BackendMessage[];
  current_intent_name?: string | null;
};

export type ConversationResponse = {
  conversation_id: string;
  reply: { role: string; content: string; timestamp: string | null };
  tool_invoked: BackendTool | null;
  requires_confirmation: boolean;
  confirmation_prompt: string;
  status: "success" | "clarification" | "ended" | "error";
  selected_intent: string;
  selected_agent: string;
  locked_intent_name: string | null;
  next_active_tool_id: string | null;
};

export type StreamEvent =
  | { type: "chunk"; text: string }
  | {
      type: "done";
      intent: string;
      status: "success" | "clarification" | "ended" | "error";
      selected_agent: string;
      slots: Record<string, unknown>;
      missing_slots: string[];
      conversation_id: string;
      locked_intent_name: string | null;
      next_active_tool_id: string | null;
      tool_invoked: BackendTool | null;
    }
  | { type: "error"; message: string };

type ConversationsResponse = {
  conversations: Array<{
    id: string;
    agent_id: string;
    agent_name: string;
    started_at: string;
    ended_at: string | null;
  }>;
  total: number;
};

// ---------------------------------------------------------------------------
// Adapters: frontend schema → backend wire schema
// ---------------------------------------------------------------------------

function adaptTool(tool: FrontendTool): BackendTool {
  const base = {
    id: tool.name || tool.type,
    name: tool.name,
    type: tool.type,
    description: tool.description,
    confirmation: { required: true, prompt: "" },
  };
  if (tool.type === "data_extraction") {
    return { ...base, parameters: { params: tool.params } };
  }
  if (tool.type === "agent_transfer") {
    return { ...base, parameters: { targets: tool.targets } };
  }
  return { ...base, parameters: {} };
}

function adaptAgentConfig(agent: AgentConfig): BackendAgentConfig {
  // Map FE provider id to backend LLMProvider enum, matching the voice
  // path in livekitAgentMetadata.ts (backend accepts "openai"/"google").
  const llmProvider = agent.llm.provider === "gemini" ? "google" : "openai";
  const out: BackendAgentConfig = {
    id: agent.agent_id,
    name: agent.name,
    persona: agent.instructions,
    greeting: agent.first_message.message,
    stt: { provider: agent.stt.provider, language: "multi", model: agent.stt.model },
    llm: { provider: llmProvider, model: agent.llm.model },
    tts: { provider: agent.tts.provider, voice_id: agent.tts.voice_id, model: agent.tts.model },
    tools: agent.tools.map(adaptTool),
  };
  if (agent.persona_constraints) {
    out.persona_constraints = agent.persona_constraints;
  }
  if (agent.context_limit) {
    out.context_limit = agent.context_limit;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Send one conversation turn to the backend and return the assistant reply.
 *
 * @param agent        - The active AgentConfig (from the config editor or preset)
 * @param transcript   - All turns so far, INCLUDING the latest user turn
 * @param conversationId - Stable ID for this call session
 * @param signal       - Optional AbortSignal to cancel an in-flight request
 */
export async function sendMessage(
  agent: AgentConfig,
  transcript: LiveTranscriptTurn[],
  conversationId: string,
  signal?: AbortSignal,
  lockedIntentName?: string | null,
): Promise<ConversationResponse> {
  // STEP A: Map transcript -> backend Message[]
  const messages: BackendMessage[] = transcript.map((turn) => ({
    role: turn.role === "user" ? "user" : "assistant",
    content: turn.text,
  }));

  // STEP B: adaptAgentConfig(agent) — maps frontend fields -> backend fields
  const body: ConversationRequest = {
    conversation_id: conversationId,
    agent_config: adaptAgentConfig(agent),
    messages,
    current_intent_name: lockedIntentName ?? null,
  };

  const res = await fetch("/api/v1/conversations/process", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }

  const data: ConversationResponse = await res.json();
  return data;
}

/**
 * Get all conversations for the current user.
 * Called on page load to restore previous conversations.
 *
 * @returns Promise with conversations list
 */
export async function getConversations(): Promise<ConversationsResponse> {
  const response = await fetch("/api/v1/conversations");
  if (!response.ok) {
    throw new Error("Failed to fetch conversations");
  }
  return response.json();
}

/**
 * Stream one conversation turn via POST /api/v1/conversations/stream (SSE).
 *
 * Yields typed StreamEvent values as they arrive. Callers should iterate with
 * `for await` and handle "chunk", "done", and "error" variants. Malformed
 * SSE lines are silently skipped.
 */
export async function* sendMessageStream(
  agent: AgentConfig,
  transcript: LiveTranscriptTurn[],
  conversationId: string,
  signal?: AbortSignal,
  lockedIntentName?: string | null,
): AsyncGenerator<StreamEvent> {
  const messages: BackendMessage[] = transcript.map((turn) => ({
    role: turn.role === "user" ? "user" : "assistant",
    content: turn.text,
  }));

  const body: ConversationRequest = {
    conversation_id: conversationId,
    agent_config: adaptAgentConfig(agent),
    messages,
    current_intent_name: lockedIntentName ?? null,
  };

  const res = await fetch("/api/v1/conversations/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }

  if (!res.body) {
    throw new Error("Response body is null");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";

      for (const part of parts) {
        for (const line of part.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          const json = line.slice(6).trim();
          if (!json) continue;
          try {
            yield JSON.parse(json) as StreamEvent;
          } catch {
            // malformed line — skip
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
