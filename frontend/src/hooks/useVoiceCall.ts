/**
 * Owns the high-level voice-call lifecycle: idle → connecting → in-call →
 * ended. The phase-level states (`idle_in_call`, `recording`, `thinking`,
 * `speaking`, `reconnecting`) are computed from real LiveKit events
 * inside the room (see `VoiceSession` component) and pushed back into
 * this hook via `setPhase`. Keeping the lifecycle and the phase
 * decoupled means the hook can be used outside a `LiveKitRoom` (e.g.
 * before the room mounts) and the phase logic stays in one place.
 *
 * NOT a generic chat hook — it's tightly coupled to the
 * `ConversationalChat` surface.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { getConversationHistory } from "@/lib/conversationApi";
import { fetchLiveKitToken } from "@/lib/livekitToken";
import type { CallStatus, ConfirmationPromptState, LiveTranscriptTurn } from "@/types/callState";

export type VoiceCallStartOptions = {
  /** `AgentConfig`-shaped JSON for the worker (see `buildLiveKitWorkerMetadata`). */
  tokenMetadata?: Record<string, unknown>;
  /** Agent greeting to show immediately in the transcript before TTS arrives. */
  greeting?: string;
};

type LiveKitCredentials = { url: string; token: string };

export type VoiceCallApi = {
  status: CallStatus;
  transcript: LiveTranscriptTurn[];
  confirmation: ConfirmationPromptState | null;
  conversationId: string;
  livekitCredentials: LiveKitCredentials | null;
  micError: string | null;
  sessionEndReason: string | null;
  clearSessionEndReason: () => void;
  /** Tear down the session with a reason banner when the room/agent drops unexpectedly. */
  reportConnectionLost: (reason: string) => void;

  /** Begin a new call: fetch token, transition to `connecting`. */
  start: (options?: VoiceCallStartOptions) => string;
  /** End the call: tear down LiveKit, transition to `ended`. */
  end: () => void;
  /** Reset everything back to the pre-call surface. */
  restart: () => void;

  /** Confirmation-prompt helpers. */
  triggerConfirmation: (prompt: ConfirmationPromptState) => void;
  approveConfirmation: () => void;
  denyConfirmation: () => void;

  /** Called from inside LiveKitRoom to push phase changes upward. */
  setPhase: (phase: CallStatus) => void;
  /** Called from inside LiveKitRoom on permission errors. */
  setMicError: (message: string | null) => void;

  /** Sync the backend-assigned conversation ID and persist it to localStorage. */
  updateConversationId: (id: string) => void;

  /** Append a final user transcript turn (called when STT segment is final). */
  appendUserTurn: (text: string) => void;
  /** Append an assistant transcript turn. */
  appendAssistantTurn: (text: string) => void;
  /** Update an in-flight transcript turn by id (interim segments). */
  upsertTurnById: (id: string, role: "user" | "assistant", text: string, isFinal?: boolean) => void;
  /**
   * Insert a new assistant turn BEFORE any consecutive user turns at the tail
   * of the array. Corrects the race where Deepgram delivers the user transcript
   * before the agent's sync_transcription text stream sends its first word.
   */
  insertAssistantTurnBeforeUsers: (id: string, text: string, isFinal?: boolean) => void;
  /** Remove a turn by id (e.g. discard a failed user turn). */
  removeTurnById: (id: string) => void;
};

const CONV_ID_STORAGE_KEY = "taskorbit_conversation_id";
const CONNECTING_TIMEOUT_MS = 800;
// Brief wind-down after End is pressed: the room is torn down immediately, but
// we hold an "ending" state this long before the ended summary so the hang-up
// feels intentional instead of an instant cut.
const ENDING_BEAT_MS = 600;
const INACTIVITY_TIMEOUT_MS =
  Number(import.meta.env.VITE_INACTIVITY_TIMEOUT_MINUTES ?? 7) * 60 * 1000;
const SESSION_MAX_MS = Number(import.meta.env.VITE_SESSION_MAX_MINUTES ?? 30) * 60 * 1000;

function generateConversationId(): string {
  return `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function generateId(prefix: string): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function useVoiceCall(): VoiceCallApi {
  const [status, setStatus] = useState<CallStatus>("idle");
  const [transcript, setTranscript] = useState<LiveTranscriptTurn[]>([]);
  const [confirmation, setConfirmation] = useState<ConfirmationPromptState | null>(null);
  const [conversationId, setConversationId] = useState<string>(
    () => localStorage.getItem(CONV_ID_STORAGE_KEY) ?? "",
  );
  const [livekitCredentials, setLivekitCredentials] = useState<LiveKitCredentials | null>(null);
  const [micError, setMicError] = useState<string | null>(null);
  const [sessionEndReason, setSessionEndReason] = useState<string | null>(null);

  const timerRef = useRef<number | null>(null);
  const endingTimerRef = useRef<number | null>(null);
  const sessionTimerRef = useRef<number | null>(null);
  const inactivityTimerRef = useRef<number | null>(null);
  const statusRef = useRef<CallStatus>(status);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      if (endingTimerRef.current !== null) window.clearTimeout(endingTimerRef.current);
      if (sessionTimerRef.current !== null) window.clearTimeout(sessionTimerRef.current);
      if (inactivityTimerRef.current !== null) window.clearTimeout(inactivityTimerRef.current);
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (conversationId) {
      localStorage.setItem(CONV_ID_STORAGE_KEY, conversationId);
    } else {
      localStorage.removeItem(CONV_ID_STORAGE_KEY);
    }
  }, [conversationId]);

  const updateConversationId = useCallback((id: string) => {
    setConversationId(id);
  }, []);

  // On mount, if a previous conversation ID is stored, fetch its history and
  // restore the transcript so the user sees prior turns on reload.
  useEffect(() => {
    const storedId = localStorage.getItem(CONV_ID_STORAGE_KEY);
    if (!storedId) return;

    void getConversationHistory(storedId)
      .then((history) => {
        const turns: LiveTranscriptTurn[] = history.messages.map((m) => ({
          id: `restored-${m.id}`,
          role: m.role === "user" ? "user" : "assistant",
          text: m.content,
          isFinal: true,
        }));
        setTranscript(turns);
      })
      .catch(() => {
        // Backend unreachable or conversation deleted — start clean.
        localStorage.removeItem(CONV_ID_STORAGE_KEY);
        setConversationId("");
      });
  }, []); // intentionally empty — runs once on mount only

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (endingTimerRef.current !== null) {
      window.clearTimeout(endingTimerRef.current);
      endingTimerRef.current = null;
    }
  }, []);

  const clearSessionTimers = useCallback(() => {
    if (sessionTimerRef.current !== null) {
      window.clearTimeout(sessionTimerRef.current);
      sessionTimerRef.current = null;
    }
    if (inactivityTimerRef.current !== null) {
      window.clearTimeout(inactivityTimerRef.current);
      inactivityTimerRef.current = null;
    }
  }, []);

  const clearSessionEndReason = useCallback(() => setSessionEndReason(null), []);

  // Inline restart body to avoid a circular dependency between restart ↔ handleSessionTimeout.
  const handleSessionTimeout = useCallback(
    (reason: string) => {
      clearTimer();
      clearSessionTimers();
      abortRef.current?.abort();
      setSessionEndReason(reason);
      setTranscript([]);
      setConversationId("");
      setConfirmation(null);
      setLivekitCredentials(null);
      setMicError(null);
      setStatus("idle");
    },
    [clearTimer, clearSessionTimers],
  );

  // Called by the room bridge when the LiveKit room drops or the agent
  // participant leaves after having joined (e.g. the worker crashed). Reuses
  // the timeout teardown so the user gets a clear reason banner and a clean
  // pre-call surface instead of a frozen "live" session with a stale pill.
  const reportConnectionLost = useCallback(
    (reason: string) => handleSessionTimeout(reason),
    [handleSessionTimeout],
  );

  const appendUserTurn = useCallback((text: string) => {
    setTranscript((t) => [...t, { id: generateId("u"), role: "user", text }]);
  }, []);

  const appendAssistantTurn = useCallback((text: string) => {
    setTranscript((t) => [...t, { id: generateId("a"), role: "assistant", text }]);
  }, []);

  // Used by the transcription hook for streaming interim segments —
  // the same segment id arrives multiple times while STT is processing,
  // each one with a longer text. Replace the existing turn rather than
  // appending a new one each time.
  const upsertTurnById = useCallback(
    (id: string, role: "user" | "assistant", text: string, isFinal?: boolean) => {
      setTranscript((turns) => {
        const existing = turns.findIndex((t) => t.id === id);
        if (existing === -1) {
          return [...turns, { id, role, text, isFinal }];
        }
        const next = turns.slice();
        next[existing] = { id, role, text, isFinal };
        return next;
      });
    },
    [],
  );

  const insertAssistantTurnBeforeUsers = useCallback(
    (id: string, text: string, isFinal?: boolean) => {
      setTranscript((turns) => {
        const existing = turns.findIndex((t) => t.id === id);
        if (existing !== -1) {
          const next = turns.slice();
          next[existing] = { id, role: "assistant", text, isFinal };
          return next;
        }
        // Walk back from the tail and find the earliest consecutive user turn.
        // Insert the new agent turn before that run so it always precedes the
        // user turns that raced ahead of the agent's text stream.
        let insertIdx = turns.length;
        for (let i = turns.length - 1; i >= 0; i--) {
          if (turns[i].role === "user") {
            insertIdx = i;
          } else {
            break;
          }
        }
        const next = turns.slice();
        next.splice(insertIdx, 0, { id, role: "assistant", text, isFinal });
        return next;
      });
    },
    [],
  );

  const removeTurnById = useCallback((id: string) => {
    setTranscript((turns) => turns.filter((t) => t.id !== id));
  }, []);

  const start = useCallback(
    (options?: VoiceCallStartOptions) => {
      clearTimer();
      clearSessionTimers();
      abortRef.current?.abort();

      const newConvId = generateConversationId();
      setConversationId(newConvId);
      setTranscript(
        options?.greeting ? [{ id: "greeting", role: "assistant", text: options.greeting }] : [],
      );
      setConfirmation(null);
      setLivekitCredentials(null);
      setMicError(null);
      setSessionEndReason(null);
      setStatus("connecting");

      const controller = new AbortController();
      abortRef.current = controller;

      void fetchLiveKitToken("user", newConvId, controller.signal, options?.tokenMetadata)
        .then((creds) => {
          if (statusRef.current === "idle" || statusRef.current === "ended") {
            return;
          }
          setLivekitCredentials({ url: creds.url, token: creds.token });
        })
        .catch((err) => {
          if ((err as Error).name === "AbortError") return;
          setMicError(`Could not start session: ${(err as Error).message}`);
          setStatus("ended");
        });

      // Fallback: if room dispatch hasn't reported a phase yet within the
      // connecting grace period, surface `idle_in_call` so the UI doesn't
      // get stuck on the spinner. Real phase events from LiveKit will
      // overwrite this almost immediately.
      timerRef.current = window.setTimeout(() => {
        if (statusRef.current !== "connecting") return;
        setStatus("idle_in_call");
      }, CONNECTING_TIMEOUT_MS);

      sessionTimerRef.current = window.setTimeout(() => {
        handleSessionTimeout("Session time limit reached. Your session has been closed.");
      }, SESSION_MAX_MS);

      inactivityTimerRef.current = window.setTimeout(() => {
        handleSessionTimeout(
          "Session closed due to inactivity (no speech detected for 7 minutes).",
        );
      }, INACTIVITY_TIMEOUT_MS);

      return newConvId;
    },
    [clearTimer, clearSessionTimers, handleSessionTimeout],
  );

  const end = useCallback(() => {
    clearTimer();
    clearSessionTimers();
    abortRef.current?.abort();
    setConversationId("");
    setConfirmation(null);
    // Tear the room down immediately (audio + mic stop now), but hold a brief
    // "ending" wind-down before the ended summary so the hang-up feels smooth
    // instead of an instant cut.
    setLivekitCredentials(null);
    setStatus("ending");
    endingTimerRef.current = window.setTimeout(() => {
      setStatus("ended");
    }, ENDING_BEAT_MS);
  }, [clearTimer, clearSessionTimers]);

  const restart = useCallback(() => {
    clearTimer();
    clearSessionTimers();
    abortRef.current?.abort();
    setTranscript([]);
    setConversationId("");
    setConfirmation(null);
    setLivekitCredentials(null);
    setMicError(null);
    setStatus("idle");
  }, [clearTimer, clearSessionTimers]);

  const setPhase = useCallback(
    (phase: CallStatus) => {
      // Don't override idle/ended/awaiting_confirmation from inside the room —
      // those are owned by the lifecycle layer.
      if (
        statusRef.current === "idle" ||
        statusRef.current === "ended" ||
        statusRef.current === "awaiting_confirmation"
      ) {
        return;
      }
      // Any active phase (user speaking, agent thinking/speaking) resets the
      // inactivity countdown so silence-only periods are what trigger the timeout.
      if (phase === "recording" || phase === "thinking" || phase === "speaking") {
        if (inactivityTimerRef.current !== null) {
          window.clearTimeout(inactivityTimerRef.current);
        }
        inactivityTimerRef.current = window.setTimeout(() => {
          handleSessionTimeout(
            "Session closed due to inactivity (no speech detected for 7 minutes).",
          );
        }, INACTIVITY_TIMEOUT_MS);
      }
      setStatus(phase);
    },
    [handleSessionTimeout],
  );

  const triggerConfirmation = useCallback(
    (prompt: ConfirmationPromptState) => {
      clearTimer();
      setConfirmation(prompt);
      setStatus("awaiting_confirmation");
    },
    [clearTimer],
  );

  const approveConfirmation = useCallback(() => {
    setConfirmation(null);
    setStatus("thinking");
  }, []);

  const denyConfirmation = useCallback(() => {
    setConfirmation(null);
    setStatus("thinking");
  }, []);

  return {
    status,
    transcript,
    confirmation,
    conversationId,
    livekitCredentials,
    micError,
    sessionEndReason,
    clearSessionEndReason,
    reportConnectionLost,
    start,
    end,
    restart,
    triggerConfirmation,
    approveConfirmation,
    denyConfirmation,
    setPhase,
    setMicError,
    updateConversationId,
    appendUserTurn,
    appendAssistantTurn,
    upsertTurnById,
    insertAssistantTurnBeforeUsers,
    removeTurnById,
  };
}
