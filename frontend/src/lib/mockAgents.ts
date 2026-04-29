import type { AgentConfig } from "@/types/agentConfig";

/**
 * SARAH_AGENT — Meisterwerk's reference example shared by Preet on
 * 2026-04-27 (Slack #stakeholder). Used as the default form value so the
 * config screen always loads with a realistic, end-to-end agent ready to
 * inspect or save.
 */
export const SARAH_AGENT: AgentConfig = {
  agent_id: "preet-agent",
  name: "Sarah",
  instructions: `# PERSONA
You are Sarah, a friendly and professional customer service agent for TechStore.

# ROLE
You are the main orchestrator who guides customers through the service flow:
1. First, determine if they are a new or existing customer
2. For new customers: collect name, email, and phone number
3. For existing customers: verify their customer ID and name
4. Use the data extraction tools to save collected information

# GUARDRAILS
- Keep responses concise (1-2 sentences) - this is a voice call
- Be warm and helpful, not robotic
- Speak naturally and conversationally
- Collect information one piece at a time, not all at once
- Always confirm information before proceeding
- Use the collect_user_info tool to save data as you collect it`,
  first_message: {
    type: "text",
    message:
      "Hi there! I'm Sarah from TechStore customer support. Before we begin, are you a new customer or do you already have an account with us?",
    prompt: "",
  },
  variables: {
    name: "Sarah",
  },
  stt: {
    provider: "deepgram",
    model: "nova-3",
  },
  tts: {
    provider: "elevenlabs",
    model: "eleven_turbo_v2",
    voice_id: "v3V1d2rk6528UrLKRuy8",
  },
  llm: {
    provider: "openai",
    model: "gpt-4.1-mini",
  },
  tools: [
    {
      type: "data_extraction",
      name: "collect_user_info",
      description:
        "Use this tool to save customer information as you collect it during the conversation. Can be called multiple times to save different pieces of data.",
      params: [
        {
          variable_name: "full_name",
          description: "Customer's full name",
          type: "string",
          required: false,
        },
        {
          variable_name: "phone",
          description: "Customer's phone number",
          type: "string",
          required: false,
        },
        {
          variable_name: "email",
          description: "Customer's email address",
          type: "string",
          required: false,
        },
        {
          variable_name: "customer_id",
          description: "Existing customer's account ID or customer number",
          type: "string",
          required: false,
        },
        {
          variable_name: "is_new_customer",
          description: "True if new customer, false if existing customer",
          type: "boolean",
          required: false,
        },
      ],
    },
  ],
  engine: {},
};

/**
 * EMPTY_AGENT — used by the "Reset to empty" footer action so the user
 * sees the required-field validation kick in (helps demo the form's
 * validation states quickly).
 */
export const EMPTY_AGENT: AgentConfig = {
  agent_id: "",
  name: "",
  instructions: "",
  first_message: { type: "text", message: "", prompt: "" },
  variables: {},
  stt: { provider: "deepgram", model: "" },
  tts: { provider: "elevenlabs", model: "", voice_id: "" },
  llm: { provider: "openai", model: "" },
  tools: [],
  engine: {},
};
