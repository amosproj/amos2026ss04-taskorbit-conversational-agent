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

import {
  END_CALL_DEFAULT_DESCRIPTION,
  type AgentConfig,
  type ConfirmationsConfig,
  type ToolDefinition as FrontendTool,
} from "@/types/agentConfig";
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
  workflow_dependencies: string[];
  workflow_rules?: WorkflowRule[];
  allowed_handoffs: string[];
};

type WorkflowRuleWhen = {
  intent?: string;
  agent_name?: string;
  else?: boolean;
};

type WorkflowRule = {
  when: WorkflowRuleWhen;
  dependencies: string[];
};

type BackendMessage = { role: "user" | "assistant" | "system"; content: string };

type ManualTransfer = {
  target_agent_id?: string;
  target_agent_name?: string;
};

type ConversationRequest = {
  conversation_id: string;
  agent_config: BackendAgentConfig;
  messages: BackendMessage[];
  current_intent_name?: string | null;
  selected_agent?: string | null;
  confirmation_id?: string | null;
  decision?: "confirm" | "reject" | null;
  completed_workflow_steps: string[];
  manual_transfer?: ManualTransfer | null;
};

export type ConversationResponse = {
  conversation_id: string;
  reply: { role: string; content: string; timestamp: string | null };
  tool_invoked: BackendTool | null;
  confirmation?: { confirmation_id: string; action: string; description: string };
  status:
    | "success"
    | "clarification"
    | "ended"
    | "error"
    | "confirmation_required"
    | "rejected"
    | "workflow_confirmation_required"
    | "handoff_blocked";
  selected_intent: string;
  selected_agent: string;
  locked_intent_name: string | null;
  next_active_tool_id: string | null;
  completed_workflow_steps: string[];
};

export type StreamEvent =
  | { type: "chunk"; text: string }
  | {
      type: "done";
      intent: string;
      status:
        | "success"
        | "clarification"
        | "ended"
        | "error"
        | "confirmation_required"
        | "rejected"
        | "workflow_confirmation_required"
        | "handoff_blocked";
      selected_agent: string;
      slots: Record<string, unknown>;
      missing_slots: string[];
      conversation_id: string;
      locked_intent_name: string | null;
      next_active_tool_id: string | null;
      tool_invoked: BackendTool | null;
      completed_workflow_steps: string[];
      confirmation?: { confirmation_id: string; action: string; description: string } | null;
      /** Full assistant reply when no stream chunks were sent (e.g. workflow confirmation). */
      reply?: string | null;
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

export type ConversationHistory = {
  conversation_id: string;
  agent_id: string;
  agent_name: string;
  started_at: string;
  ended_at: string | null;
  messages: Array<{ id: number; role: string; content: string; created_at: string }>;
  tool_executions: Array<{
    id: number;
    tool_id: string;
    tool_type: string;
    confirmed: boolean;
    executed_at: string;
    result: Record<string, unknown> | null;
  }>;
  slot_extractions: Array<{
    id: number;
    tool_id: string;
    field_name: string;
    field_value: string | null;
    extracted_at: string;
  }>;
};

// ---------------------------------------------------------------------------
// Adapters: frontend schema → backend wire schema
// ---------------------------------------------------------------------------

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
  if (tool.type === "external_api") {
    // External API tools (#66) carry the full backend config in
    // `parameters` already (request / response / auth / error_mapping /
    // args_schema), so pass it through verbatim.
    return { ...base, parameters: tool.parameters };
  }
  return { ...base, parameters: {} };
}

function adaptAgentConfig(agent: AgentConfig): BackendAgentConfig {
  // Map FE provider id to backend LLMProvider enum value.
  // "gemini" → "google", "openrouter" → "openrouter", "ollama" → "ollama", "openai" → "openai".
  const llmProvider =
    agent.llm.provider === "gemini"
      ? "google"
      : agent.llm.provider === "openrouter"
        ? "openrouter"
        : agent.llm.provider === "ollama"
          ? "ollama"
          : "openai";
  const out: BackendAgentConfig = {
    id: agent.agent_id,
    name: agent.name,
    persona: agent.instructions,
    greeting: agent.first_message.message,
    stt: { provider: agent.stt.provider, language: "multi", model: agent.stt.model },
    llm: { provider: llmProvider, model: agent.llm.model },
    tts: { provider: agent.tts.provider, voice_id: agent.tts.voice_id, model: agent.tts.model },
    tools: agent.tools.map((t) => adaptTool(t, agent.confirmations)),
    workflow_dependencies: agent.workflow_dependencies,
    allowed_handoffs: agent.allowed_handoffs,
  };
  if (agent.workflow_rules?.length) {
    out.workflow_rules = agent.workflow_rules;
  }
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
  confirmationId?: string | null,
  decision?: "confirm" | "reject" | null,
  completedWorkflowSteps: string[] = [],
  selectedAgent?: string | null,
  manualTransfer?: ManualTransfer | null,
): Promise<ConversationResponse> {
  // STEP A: Map transcript -> backend Message[]
  const messages: BackendMessage[] = transcript.map((turn) => ({
    role: turn.role,
    content: turn.text,
  }));

  // STEP B: adaptAgentConfig(agent) — maps frontend fields -> backend fields
  const body: ConversationRequest = {
    conversation_id: conversationId,
    agent_config: adaptAgentConfig(agent),
    messages,
    current_intent_name: lockedIntentName ?? null,
    selected_agent: selectedAgent ?? null,
    confirmation_id: confirmationId ?? null,
    decision: decision ?? null,
    completed_workflow_steps: completedWorkflowSteps,
    manual_transfer: manualTransfer ?? null,
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
  confirmationId?: string | null,
  decision?: "confirm" | "reject" | null,
  completedWorkflowSteps?: string[],
  selectedAgent?: string | null,
  manualTransfer?: ManualTransfer | null,
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
    confirmation_id: confirmationId ?? null,
    decision: decision ?? null,
    completed_workflow_steps: completedWorkflowSteps ?? [],
    selected_agent: selectedAgent ?? null,
    manual_transfer: manualTransfer ?? null,
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

/**
 * Permanently delete a conversation and all its messages.
 * Throws on network error or non-2xx response.
 */
export async function deleteConversation(conversationId: string): Promise<void> {
  const res = await fetch(`/api/v1/conversations/${conversationId}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }
}

/**
 * Fetch full history for a single conversation — messages, tool executions,
 * and slot extractions. Used on reload to restore a previous session.
 */
export async function getConversationHistory(conversationId: string): Promise<ConversationHistory> {
  const response = await fetch(`/api/v1/conversations/${conversationId}/history`);
  if (!response.ok) {
    throw new Error(`Failed to fetch history for conversation ${conversationId}`);
  }
  return response.json();
}
