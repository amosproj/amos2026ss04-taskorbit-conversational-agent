/**
 * Lives inside `<LiveKitRoom>` and translates room-level events into
 * the call-status enum that `useVoiceCall` understands. This is the
 * single integration point between the LiveKit world (room, agent
 * participant, transcription streams) and the React state machine the
 * UI cares about.
 *
 * The component renders nothing on its own; everything is side effects
 * via the supplied callbacks.
 */

import { useVoiceAssistant } from "@livekit/components-react";
import { useCallback, useEffect, useRef } from "react";

import { useAgentHandoff } from "@/hooks/useAgentHandoff";
import { type TranscriptionSegment, useAgentTranscription } from "@/hooks/useAgentTranscription";
import { useConnectionStatus } from "@/hooks/useConnectionStatus";
import { useRoutedAgent } from "@/hooks/useRoutedAgent";
import { useSessionEnded } from "@/hooks/useSessionEnded";
import { useVoiceConfirmation } from "@/hooks/useVoiceConfirmation";
import type { CallStatus, ConfirmationPromptState } from "@/types/callState";

// A dead worker shows up as a sustained "connecting" agent state (LiveKit keeps
// trying to redispatch it), so we wait this long before declaring the call
// lost — long enough that a genuine transient reconnect recovers first.
const CONNECTION_LOST_GRACE_MS = 8_000;

type Props = {
  status: CallStatus;
  onPhase: (phase: CallStatus) => void;
  onSegment: (segment: TranscriptionSegment) => void;
  onHandoff?: (agentName: string) => void;
  onAgentRouted?: (agentName: string) => void;
  onSessionEnded?: () => void;
  onConnectionLost: (reason: string) => void;
  onConfirmationPending?: (prompt: ConfirmationPromptState) => void;
  onConfirmationCleared?: () => void;
};

export function VoiceSessionBridge({
  status,
  onPhase,
  onSegment,
  onHandoff,
  onAgentRouted,
  onSessionEnded,
  onConnectionLost,
  onConfirmationPending,
  onConfirmationCleared,
}: Props) {
  const connection = useConnectionStatus();
  const { state: agentState } = useVoiceAssistant();

  // Keep the latest status in a ref so transcription/agent-state
  // effects can read it without re-running every time it changes.
  const statusRef = useRef(status);
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  // Connection drops take precedence over phase so the user always
  // knows when the room is in a degraded state.
  useEffect(() => {
    if (connection === "reconnecting") {
      onPhase("reconnecting");
    } else if (connection === "connected" && statusRef.current === "reconnecting") {
      // After we recover, fall back to a neutral in-call state. The
      // user can re-tap the mic to resume their turn.
      onPhase("idle_in_call");
    }
  }, [connection, onPhase]);

  // Track whether the room and agent each fully came up. At startup the
  // connection is briefly not-yet-connected and the agent briefly reports
  // "disconnected" before it joins, so a drop only counts once each has
  // actually been up — otherwise every call would self-terminate on connect.
  const roomConnectedRef = useRef(false);
  const agentJoinedRef = useRef(false);
  const connectionLostFiredRef = useRef(false);
  useEffect(() => {
    if (connection === "connected") roomConnectedRef.current = true;
  }, [connection]);
  useEffect(() => {
    if (
      agentState === "initializing" ||
      agentState === "listening" ||
      agentState === "thinking" ||
      agentState === "speaking"
    ) {
      agentJoinedRef.current = true;
    }
  }, [agentState]);

  // Surface an unexpected loss so the status pill never freezes on a dead call
  // (#181). Key subtlety: when the worker dies, LiveKit does NOT report the
  // agent as "disconnected" — it reports "connecting" (it keeps trying to
  // redispatch) and stays there. So once the agent has joined, a sustained
  // "connecting"/"disconnected" agentState, or a full room drop, means the call
  // is dead. We debounce by CONNECTION_LOST_GRACE_MS so a genuine transient
  // reconnect (which recovers to an active state, clearing the timer) doesn't
  // false-trigger. A deliberate hang-up unmounts this component first, so this
  // fires only on real drops, once per session, and the reused timeout teardown
  // shows a reason banner and returns to the pre-call surface.
  useEffect(() => {
    if (connectionLostFiredRef.current) return;
    const roomDropped = connection === "disconnected" && roomConnectedRef.current;
    const agentDropped =
      agentJoinedRef.current && (agentState === "connecting" || agentState === "disconnected");
    if (!roomDropped && !agentDropped) return;
    if (statusRef.current === "idle" || statusRef.current === "ended") return;
    const timer = window.setTimeout(() => {
      if (connectionLostFiredRef.current) return;
      if (statusRef.current === "idle" || statusRef.current === "ended") return;
      connectionLostFiredRef.current = true;
      onConnectionLost(
        roomDropped
          ? "The call disconnected unexpectedly. Please start a new session."
          : "The agent disconnected unexpectedly. Please start a new session.",
      );
    }, CONNECTION_LOST_GRACE_MS);
    return () => window.clearTimeout(timer);
  }, [connection, agentState, onConnectionLost]);

  // Drive thinking/speaking purely from the agent's reported state. We
  // don't fight the user-driven `recording` / `idle_in_call` phases,
  // so they take precedence even if the agent briefly reports a
  // different state during transitions.
  useEffect(() => {
    if (statusRef.current === "recording" || statusRef.current === "reconnecting") {
      return;
    }
    if (agentState === "speaking") {
      onPhase("speaking");
      return;
    }
    if (agentState === "thinking" || agentState === "initializing") {
      onPhase("thinking");
      return;
    }
    if (agentState === "listening") {
      // The agent reports "listening" both before a turn AND during the STT gap
      // right after the user commits (Deepgram's ~1.4s delay before it reports
      // "thinking"). While we are in "thinking" (the user committed and is
      // waiting on a reply), do NOT fall back to idle_in_call: that would flash
      // "Listening…" (idle -> auto-restart -> recording) instead of holding
      // "Processing…" until the reply arrives. Only the post-speaking listening
      // transition should return us to idle to re-arm the mic. (#153)
      if (statusRef.current !== "thinking") {
        onPhase("idle_in_call");
      }
    }
  }, [agentState, onPhase]);

  const handleSegment = useCallback(
    (segment: TranscriptionSegment) => {
      onSegment(segment);
    },
    [onSegment],
  );
  useAgentTranscription(handleSegment);

  const handleHandoff = useCallback(
    (agentName: string) => {
      onHandoff?.(agentName);
    },
    [onHandoff],
  );
  useAgentHandoff(handleHandoff);

  const handleAgentRouted = useCallback(
    (agentName: string) => {
      onAgentRouted?.(agentName);
    },
    [onAgentRouted],
  );
  useRoutedAgent(handleAgentRouted);

  const handleSessionEnded = useCallback(() => {
    onSessionEnded?.();
  }, [onSessionEnded]);
  useSessionEnded(handleSessionEnded);

  const handleConfirmationPending = useCallback(
    (prompt: ConfirmationPromptState) => {
      onConfirmationPending?.(prompt);
    },
    [onConfirmationPending],
  );
  const handleConfirmationCleared = useCallback(() => {
    onConfirmationCleared?.();
  }, [onConfirmationCleared]);
  useVoiceConfirmation(handleConfirmationPending, handleConfirmationCleared);

  return null;
}
