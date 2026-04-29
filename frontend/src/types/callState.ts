/**
 * Call surface state machine. Sprint 2 mocks the transitions with
 * setTimeout; Sprint 3 (#14, #15, #26) will drive the same states from
 * LiveKit room events without changing the component shapes.
 *
 * States map to architecture §4.1 phases:
 * - `idle`               — no session yet; show agent identity + diagnostics.
 * - `connecting`         — Start clicked; LiveKit room join in flight.
 * - `listening`          — agent worker is open to user input (STT active).
 * - `thinking`           — orchestrator/LLM generating the next response.
 * - `speaking`           — TTS streaming the agent's reply back.
 * - `awaiting_confirmation` — agent paused on a sensitive tool call until
 *                            the user explicitly approves or denies it.
 * - `ended`              — call closed; transcript is read-only and routes
 *                          to History.
 */
export type CallStatus =
  | "idle"
  | "connecting"
  | "listening"
  | "thinking"
  | "speaking"
  | "awaiting_confirmation"
  | "ended";

/**
 * One turn of the live transcript. Intentionally narrower than the
 * History `TranscriptTurn` — there's no need for cross-turn linkage in
 * the live surface; History's turn IDs are persistent and queryable, the
 * live ones are volatile and only matter for the current session.
 */
export type LiveTranscriptTurn = {
  id: string;
  role: "user" | "assistant";
  text: string;
};

/**
 * Active confirmation request shown to the user mid-call. When non-null,
 * the call surface enters `awaiting_confirmation` and renders the prompt
 * in place of the normal CallControls. Approving fires the underlying
 * tool call; denying skips it. Either way the response is recorded for
 * History.
 */
export type ConfirmationPromptState = {
  id: string;
  tool_name: string;
  prompt: string;
};
