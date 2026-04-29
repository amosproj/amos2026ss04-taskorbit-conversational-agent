/**
 * AgentConfig — the JSON contract shared by Meisterwerk (Preet, 2026-04-27).
 *
 * The required core mirrors the Sarah / TechStore example exactly so the
 * form is a faithful editor for the schema the backend will eventually
 * consume.
 *
 * The optional fields below (`confirmations`, `language`, `vad`) are NOT
 * in Preet's example but ARE listed in the team's architecture document
 * (§4.1 — confirmations, multilingual interaction, VAD via Cerebrio).
 * They are kept optional so saving an unedited Sarah preset round-trips
 * byte-for-byte to Preet's schema; the form only emits them when the user
 * touches them.
 */

export type SttProvider = "deepgram";
export type TtsProvider = "elevenlabs";
export type LlmProvider = "openai" | "gemini";

export type ParamType = "string" | "number" | "boolean" | "date";

export type ToolParam = {
  variable_name: string;
  description: string;
  type: ParamType;
  required: boolean;
};

/**
 * ToolDefinition — discriminated union over the three tool types listed
 * by the architecture document (Agent Pool: Greeting, Data Extraction,
 * Handoff). Today only `data_extraction` has a documented JSON shape from
 * Meisterwerk; `end_call` and `agent_transfer` use placeholder shapes
 * pending Preet's schema for them. The shape stays narrow enough that
 * extending it later is additive, not breaking.
 */
export type DataExtractionTool = {
  type: "data_extraction";
  name: string;
  description: string;
  params: ToolParam[];
};

export type EndCallTool = {
  type: "end_call";
  name: string;
  description: string;
};

export type AgentTransferTool = {
  type: "agent_transfer";
  name: string;
  description: string;
  targets: string[];
};

export type ToolDefinition = DataExtractionTool | EndCallTool | AgentTransferTool;

export type ToolType = ToolDefinition["type"];

export type FirstMessage = {
  type: "text";
  message: string;
  prompt: string;
};

/**
 * ConfirmationsConfig — architecture §4.1: "All actions require explicit
 * user confirmation". `required` is the global switch; `tools` is the
 * allow-list of tool names that bypass confirmation when empty means
 * "confirm all".
 */
export type ConfirmationsConfig = {
  required: boolean;
  tools: string[];
};

/**
 * LanguageConfig — architecture supports "multilingual interaction
 * (e.g., English/German), ensuring responses match the user's language."
 * Christoph deferred for the current sprint; structure exposed in the
 * Advanced section so the JSON contract is forward-compatible.
 */
export type LanguageConfig = {
  default: string;
  auto_detect: boolean;
  supported: string[];
};

/**
 * VadConfig — architecture lists VAD as a runtime concern; Preet flagged
 * Cerebrio as the leading library (Python-only, hence the Python backend
 * choice). Treated as Sprint-3 work but exposed here for completeness.
 */
export type VadConfig = {
  provider: "cerebrio" | "none";
  silence_threshold_ms: number;
};

export type AgentConfig = {
  agent_id: string;
  name: string;
  instructions: string;
  first_message: FirstMessage;
  variables: Record<string, string>;
  stt: { provider: SttProvider; model: string };
  tts: { provider: TtsProvider; model: string; voice_id: string };
  llm: { provider: LlmProvider; model: string };
  tools: ToolDefinition[];
  engine: Record<string, unknown>;

  // Architecture-driven optional extensions (kept off Preet's wire format
  // unless the user opts in via the Advanced/Confirmations sections):
  confirmations?: ConfirmationsConfig;
  language?: LanguageConfig;
  vad?: VadConfig;
};

/** Strip `undefined` optional sections so JSON output stays Preet-faithful. */
export function serializeAgent(agent: AgentConfig): Record<string, unknown> {
  const out: Record<string, unknown> = {
    agent_id: agent.agent_id,
    name: agent.name,
    instructions: agent.instructions,
    first_message: agent.first_message,
    variables: agent.variables,
    stt: agent.stt,
    tts: agent.tts,
    llm: agent.llm,
    tools: agent.tools,
    engine: agent.engine,
  };
  if (agent.confirmations) out.confirmations = agent.confirmations;
  if (agent.language) out.language = agent.language;
  if (agent.vad) out.vad = agent.vad;
  return out;
}

export function emptyToolByType(type: ToolType): ToolDefinition {
  switch (type) {
    case "data_extraction":
      return { type, name: "", description: "", params: [] };
    case "end_call":
      return { type, name: "end_call", description: "End the conversation gracefully when the goal is met." };
    case "agent_transfer":
      return { type, name: "transfer_to_agent", description: "Hand off the conversation to a specialised agent.", targets: [] };
  }
}
