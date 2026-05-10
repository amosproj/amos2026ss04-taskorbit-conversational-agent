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

import {
  type TranscriptionSegment,
  useAgentTranscription,
} from "@/hooks/useAgentTranscription";
import { useConnectionStatus } from "@/hooks/useConnectionStatus";
import type { CallStatus } from "@/types/callState";

type Props = {
  status: CallStatus;
  onPhase: (phase: CallStatus) => void;
  onSegment: (segment: TranscriptionSegment) => void;
};

export function VoiceSessionBridge({ status, onPhase, onSegment }: Props) {
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
      onPhase("idle_in_call");
    }
  }, [agentState, onPhase]);

  const handleSegment = useCallback(
    (segment: TranscriptionSegment) => {
      onSegment(segment);
    },
    [onSegment],
  );
  useAgentTranscription(handleSegment);

  return null;
}
