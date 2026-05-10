/**
 * Call surface state machine. Drives both UI affordances and audio
 * publish/mute semantics.
 *
 * States map to architecture §4.1 phases:
 * - `idle`               — no session yet; show agent identity + diagnostics.
 * - `connecting`         — Start clicked; LiveKit room join in flight.
 * - `idle_in_call`       — call active, mic muted, ready for the user to
 *                          tap the mic and start a turn (ChatGPT-style PTT).
 * - `recording`          — mic published; user is speaking. Captions stream
 *                          in real time. Stop mutes the mic, Send commits.
 * - `listening`          — legacy alias for `recording` retained for the
 *                          existing CallStatusIndicator visuals; the new
 *                          flow uses `recording`.
 * - `thinking`           — Send pressed; agent is producing a reply.
 * - `speaking`           — TTS streaming the agent's reply back. The user
 *                          can interrupt by tapping the mic again.
 * - `reconnecting`       — transient LiveKit drop; client is retrying.
 * - `awaiting_confirmation` — agent paused on a sensitive tool call until
 *                            the user explicitly approves or denies it.
 * - `ended`              — call closed; transcript is read-only and routes
 *                          to History.
 */
export type CallStatus =
  | "idle"
  | "connecting"
  | "idle_in_call"
  | "recording"
  | "listening"
  | "thinking"
  | "speaking"
  | "reconnecting"
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
