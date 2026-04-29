/**
 * Mock conversation history. Used by the History page until the backend
 * persists real transcripts (Sprint 3 — tickets #6 schema, #7 backend).
 *
 * Shape mirrors the PostgreSQL persistence block listed in the system
 * architecture doc: chat history (transcript), agent traces, tool calls,
 * confirmations, log records. Multilingual interaction is named in the
 * architecture too — `language` here is the BCP-47 tag the call ran in
 * (defaults to "en"; the JSON config supports auto-detect/switching).
 *
 * All entries reference the John Doe preset agent (`preet-agent` /
 * "John Doe") so the History view stays consistent with what the Agent
 * Configuration page shows by default. Tool firings are limited to
 * `data_extraction` (the only tool defined on the preset); calls end via
 * the user hanging up since the preset has no `end_call` or
 * `agent_transfer` tools wired. Confirmations are `[]` on every call
 * because the preset's `confirmations` block is off by default — but the
 * field exists so the UI can render an honest empty state. Caller names
 * are fictitious; phone numbers and email addresses use reserved test
 * ranges (`+49 30 12345xx` and `example.com`) to avoid resembling real
 * PII.
 */

/** Common fields on every tool firing — the discriminator narrows variant-specific fields below. */
type ToolFiringBase = {
  tool_name: string;
  /** ID of the transcript turn the firing was triggered from. */
  triggered_after_turn_id: string;
  status: "completed" | "failed";
};

export type DataExtractionFiring = ToolFiringBase & {
  type: "data_extraction";
  values: Record<string, string | number | boolean>;
};

export type EndCallFiring = ToolFiringBase & {
  type: "end_call";
};

export type AgentTransferFiring = ToolFiringBase & {
  type: "agent_transfer";
  /** Agent ID the call was handed off to. */
  target: string;
};

export type ToolFiring =
  | DataExtractionFiring
  | EndCallFiring
  | AgentTransferFiring;

/**
 * Architecture §4.1: "All actions require explicit user confirmation."
 * One entry per confirmation prompted during the call. Empty `[]` means
 * the agent's `confirmations` block was off — record-of-no-confirmations
 * is itself a meaningful audit signal.
 */
export type ConfirmationEvent = {
  id: string;
  tool_name: string;
  prompt: string;
  response: "approved" | "denied";
  /** ID of the transcript turn at which the confirmation was prompted. */
  prompted_at_turn_id: string;
};

export type TranscriptTurn = {
  id: string;
  role: "user" | "assistant";
  text: string;
};

export type EndedBy = "user_hangup" | "end_call_tool" | "agent_transfer";

export type Conversation = {
  id: string;
  agent_id: string;
  agent_name: string;
  caller_label: string;
  started_at: string;
  duration_seconds: number;
  ended_by: EndedBy;
  /** BCP-47 language tag the call ran in. Architecture supports runtime switching; mocks all default to "en" until multilingual lands. */
  language: string;
  transcript: TranscriptTurn[];
  tool_firings: ToolFiring[];
  confirmations: ConfirmationEvent[];
};

export const MOCK_CONVERSATIONS: Conversation[] = [
  {
    id: "conv-001",
    agent_id: "preet-agent",
    agent_name: "John Doe",
    caller_label: "Anna Müller",
    started_at: "2026-04-29T08:14:00Z",
    duration_seconds: 222,
    ended_by: "user_hangup",
    language: "en",
    transcript: [
      {
        id: "t1-1",
        role: "assistant",
        text: "Hi there! I'm John from TechStore customer support. Before we begin, are you a new customer or do you already have an account with us?",
      },
      {
        id: "t1-2",
        role: "user",
        text: "Hi, I'm new. I just want to set up an account.",
      },
      {
        id: "t1-3",
        role: "assistant",
        text: "Welcome! Could you start with your full name?",
      },
      { id: "t1-4", role: "user", text: "Anna Müller." },
      {
        id: "t1-5",
        role: "assistant",
        text: "Thanks Anna. What's the best email to reach you on?",
      },
      { id: "t1-6", role: "user", text: "anna.mueller@example.com." },
      {
        id: "t1-7",
        role: "assistant",
        text: "Got it. And a phone number for the account?",
      },
      { id: "t1-8", role: "user", text: "Plus four nine three zero one two three four five six seven." },
      {
        id: "t1-9",
        role: "assistant",
        text: "Before I save these details to your new account — name, email, and phone — can you confirm that's all correct?",
      },
      { id: "t1-10", role: "user", text: "Yes, that's correct." },
      {
        id: "t1-11",
        role: "assistant",
        text: "Perfect, I've saved all of that. Anything else I can help you with today?",
      },
      { id: "t1-12", role: "user", text: "No, that's all, thanks." },
    ],
    tool_firings: [
      {
        type: "data_extraction",
        tool_name: "collect_user_info",
        triggered_after_turn_id: "t1-10",
        status: "completed",
        values: {
          full_name: "Anna Müller",
          email: "anna.mueller@example.com",
          phone: "+49 30 1234567",
          is_new_customer: true,
        },
      },
    ],
    confirmations: [
      {
        id: "c1-1",
        tool_name: "collect_user_info",
        prompt: "Save new customer details (name, email, phone) to the account.",
        response: "approved",
        prompted_at_turn_id: "t1-9",
      },
    ],
  },
  {
    id: "conv-002",
    agent_id: "preet-agent",
    agent_name: "John Doe",
    caller_label: "Lukas Becker",
    started_at: "2026-04-28T15:42:00Z",
    duration_seconds: 168,
    ended_by: "end_call_tool",
    language: "de",
    transcript: [
      {
        id: "t2-1",
        role: "assistant",
        text: "Hallo! Ich bin John vom TechStore-Kundenservice. Bevor wir anfangen — sind Sie ein neuer Kunde oder haben Sie schon ein Konto bei uns?",
      },
      { id: "t2-2", role: "user", text: "Ich habe schon ein Konto." },
      {
        id: "t2-3",
        role: "assistant",
        text: "Sehr gut. Könnten Sie mir bitte Ihre Kundennummer geben?",
      },
      { id: "t2-4", role: "user", text: "Es ist TS Bindestrich vier acht zwei neun eins." },
      {
        id: "t2-5",
        role: "assistant",
        text: "Danke. Und zur Bestätigung — auf welchen Namen läuft das Konto?",
      },
      { id: "t2-6", role: "user", text: "Lukas Becker." },
      {
        id: "t2-7",
        role: "assistant",
        text: "Bevor ich Ihre Kontodaten zur Verifizierung speichere — Kundennummer TS-48291, Name Lukas Becker — ist das so korrekt?",
      },
      { id: "t2-8", role: "user", text: "Ja, das stimmt." },
      {
        id: "t2-9",
        role: "assistant",
        text: "Bestätigt. Ihr Konto ist verifiziert. Kann ich Ihnen sonst noch behilflich sein?",
      },
      { id: "t2-10", role: "user", text: "Nein, das war alles. Danke!" },
      {
        id: "t2-11",
        role: "assistant",
        text: "Schönen Tag noch, Lukas — auf Wiederhören!",
      },
    ],
    tool_firings: [
      {
        type: "data_extraction",
        tool_name: "collect_user_info",
        triggered_after_turn_id: "t2-8",
        status: "completed",
        values: {
          customer_id: "TS-48291",
          full_name: "Lukas Becker",
          is_new_customer: false,
        },
      },
      {
        type: "end_call",
        tool_name: "end_call",
        triggered_after_turn_id: "t2-11",
        status: "completed",
      },
    ],
    confirmations: [
      {
        id: "c2-1",
        tool_name: "collect_user_info",
        prompt: "Save existing-customer verification (customer ID, name) to the account.",
        response: "approved",
        prompted_at_turn_id: "t2-7",
      },
    ],
  },
  {
    id: "conv-003",
    agent_id: "preet-agent",
    agent_name: "John Doe",
    caller_label: "Caller · +49 30 1234588",
    started_at: "2026-04-28T11:05:00Z",
    duration_seconds: 38,
    ended_by: "user_hangup",
    language: "en",
    transcript: [
      {
        id: "t3-1",
        role: "assistant",
        text: "Hi there! I'm John from TechStore customer support. Before we begin, are you a new customer or do you already have an account with us?",
      },
      {
        id: "t3-2",
        role: "user",
        text: "Sorry, I think I dialed the wrong number.",
      },
      {
        id: "t3-3",
        role: "assistant",
        text: "No problem at all — have a good day!",
      },
    ],
    tool_firings: [],
    confirmations: [],
  },
  {
    id: "conv-004",
    agent_id: "preet-agent",
    agent_name: "John Doe",
    caller_label: "Maria Schmidt",
    started_at: "2026-04-27T17:30:00Z",
    duration_seconds: 76,
    ended_by: "user_hangup",
    language: "en",
    transcript: [
      {
        id: "t4-1",
        role: "assistant",
        text: "Hi there! I'm John from TechStore customer support. Before we begin, are you a new customer or do you already have an account with us?",
      },
      { id: "t4-2", role: "user", text: "New, I think. Can you tell me about your warranty options first?" },
      {
        id: "t4-3",
        role: "assistant",
        text: "Of course — happy to help. Could I grab your name first while we chat?",
      },
      { id: "t4-4", role: "user", text: "Maria Schmidt." },
      {
        id: "t4-5",
        role: "assistant",
        text: "Thanks Maria. So our standard warranty covers...",
      },
      { id: "t4-6", role: "user", text: "Sorry, something just came up. I'll call back later." },
      {
        id: "t4-7",
        role: "assistant",
        text: "No problem. Before you go — would you like me to save your name on file as a new customer so we can pick up faster next time?",
      },
      { id: "t4-8", role: "user", text: "No, don't save anything. I'll start fresh when I call back." },
    ],
    tool_firings: [],
    confirmations: [
      {
        id: "c4-1",
        tool_name: "collect_user_info",
        prompt: "Save partial new-customer details (name only) before the call ends.",
        response: "denied",
        prompted_at_turn_id: "t4-7",
      },
    ],
  },
  {
    id: "conv-005",
    agent_id: "preet-agent",
    agent_name: "John Doe",
    caller_label: "Felix Hoffmann",
    started_at: "2026-04-27T09:18:00Z",
    duration_seconds: 132,
    ended_by: "user_hangup",
    language: "en",
    transcript: [
      {
        id: "t5-1",
        role: "assistant",
        text: "Hi there! I'm John from TechStore customer support. Before we begin, are you a new customer or do you already have an account with us?",
      },
      {
        id: "t5-2",
        role: "user",
        text: "I'm new — I just wanted to know your store hours for the Berlin location.",
      },
      {
        id: "t5-3",
        role: "assistant",
        text: "Happy to help. Can I get your name for our records?",
      },
      { id: "t5-4", role: "user", text: "Felix Hoffmann." },
      {
        id: "t5-5",
        role: "assistant",
        text: "Thanks Felix. Our Berlin store is open Monday to Saturday, ten to eight. Anything else?",
      },
      { id: "t5-6", role: "user", text: "No, that's perfect. Thanks!" },
    ],
    tool_firings: [
      {
        type: "data_extraction",
        tool_name: "collect_user_info",
        triggered_after_turn_id: "t5-4",
        status: "completed",
        values: {
          full_name: "Felix Hoffmann",
          is_new_customer: true,
        },
      },
    ],
    confirmations: [],
  },
  {
    id: "conv-006",
    agent_id: "preet-agent",
    agent_name: "John Doe",
    caller_label: "Tobias Wagner",
    started_at: "2026-04-26T14:02:00Z",
    duration_seconds: 195,
    ended_by: "agent_transfer",
    language: "en",
    transcript: [
      {
        id: "t6-1",
        role: "assistant",
        text: "Hi there! I'm John from TechStore customer support. Before we begin, are you a new customer or do you already have an account with us?",
      },
      {
        id: "t6-2",
        role: "user",
        text: "New customer. My new laptop won't turn on at all and I just got it yesterday.",
      },
      {
        id: "t6-3",
        role: "assistant",
        text: "Sorry to hear that. Let me grab your details so I can get this on file. Your full name?",
      },
      { id: "t6-4", role: "user", text: "Tobias Wagner." },
      {
        id: "t6-5",
        role: "assistant",
        text: "And the best email to reach you?",
      },
      { id: "t6-6", role: "user", text: "tobias.wagner@example.com." },
      {
        id: "t6-7",
        role: "assistant",
        text: "Got it, I've logged the issue. Returns and replacements are handled by our billing team — let me transfer you over so they can sort the next steps.",
      },
      { id: "t6-8", role: "user", text: "Sure, thanks." },
    ],
    tool_firings: [
      {
        type: "data_extraction",
        tool_name: "collect_user_info",
        triggered_after_turn_id: "t6-6",
        status: "completed",
        values: {
          full_name: "Tobias Wagner",
          email: "tobias.wagner@example.com",
          is_new_customer: true,
        },
      },
      {
        type: "agent_transfer",
        tool_name: "transfer_to_billing",
        triggered_after_turn_id: "t6-8",
        status: "completed",
        target: "billing-agent",
      },
    ],
    confirmations: [],
  },
];
