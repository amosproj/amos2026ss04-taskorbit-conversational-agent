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

type BackendAgentConfig = {
  id: string;
  name: string;
  persona: string;
  greeting: string;
  stt: { provider: string; language: string; model: string };
  llm: { provider: string; model: string };
  tts: { provider: string; voice_id: string; model: string };
  tools: BackendTool[];
};

type BackendMessage = { role: "user" | "assistant" | "system"; content: string };

type ConversationRequest = {
  conversation_id: string;
  agent_config: BackendAgentConfig;
  messages: BackendMessage[];
};

type ConversationResponse = {
  conversation_id: string;
  reply: { role: string; content: string; timestamp: string | null };
  tool_invoked: BackendTool | null;
  requires_confirmation: boolean;
  confirmation_prompt: string;
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
  return {
    id: agent.agent_id,
    name: agent.name,
    persona: agent.instructions,
    greeting: agent.first_message.message,
    stt: { provider: agent.stt.provider, language: "multi", model: agent.stt.model },
    llm: { provider: agent.llm.provider, model: agent.llm.model },
    tts: { provider: agent.tts.provider, voice_id: agent.tts.voice_id, model: agent.tts.model },
    tools: agent.tools.map(adaptTool), //maps tools
  };
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
): Promise<string> {
  // STEP A: Map transcript -> backend Message[] 
  //Result: [{ role: "user", content: "Hello" }]  
  const messages: BackendMessage[] = transcript.map((turn) => ({
    role: turn.role === "user" ? "user" : "assistant",
    content: turn.text,
  }));

  //STEP B: adaptAgentConfig(agent) — maps frontend fields -> backend fields  
  // e.g. agent.agent_id -> id
  const body: ConversationRequest = {
    conversation_id: conversationId,
    agent_config: adaptAgentConfig(agent),
    messages,
  };

  //Request body with backend api, sent to /api/v1/conversations/process through Vite proxy
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
  return data.reply.content;
}
