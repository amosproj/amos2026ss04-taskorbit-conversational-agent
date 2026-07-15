/**
 * Subscribes to `taskorbit.confirmation_pending` data-channel packets from
 * the voice worker and drives the same Approve/Deny card the text path
 * shows, so a caller in a voice session sees WHAT the agent is about to do
 * (data extraction, agent transfer, ending the call, ...) instead of only
 * hearing a spoken "should I go ahead?".
 *
 * The voice path still resolves the actual yes/no via speech
 * (`_voice_confirmation_decision` in `llm.py`) -- this hook only drives the
 * visual card, it never submits a decision itself.
 *
 * The worker publishes one of two payload shapes on every turn:
 *   {type: "confirmation_pending", confirmation_id, action, description,
 *    tool_type, confirmation_type}
 *   {type: "confirmation_cleared"}
 *
 * Must be used inside a `<LiveKitRoom>`.
 */

import { useRoomContext } from "@livekit/components-react";
import { RoomEvent, type RemoteParticipant } from "livekit-client";
import { useEffect } from "react";

import type { ConfirmationPromptState } from "@/types/callState";

const CONFIRMATION_TOPIC = "taskorbit.confirmation_pending";

type ConfirmationPendingPayload = {
  type: "confirmation_pending";
  confirmation_id: string;
  action: string;
  description: string;
  tool_type?: string | null;
  confirmation_type?: "tool" | "workflow";
};

type ConfirmationClearedPayload = { type: "confirmation_cleared" };

function isConfirmationPendingPayload(value: unknown): value is ConfirmationPendingPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { type?: unknown }).type === "confirmation_pending" &&
    typeof (value as { confirmation_id?: unknown }).confirmation_id === "string" &&
    typeof (value as { action?: unknown }).action === "string" &&
    typeof (value as { description?: unknown }).description === "string"
  );
}

function isConfirmationClearedPayload(value: unknown): value is ConfirmationClearedPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { type?: unknown }).type === "confirmation_cleared"
  );
}

export function useVoiceConfirmation(
  onPending: (prompt: ConfirmationPromptState) => void,
  onCleared: () => void,
): void {
  const room = useRoomContext();

  useEffect(() => {
    if (!room) return;

    const handler = (
      payload: Uint8Array,
      _participant?: RemoteParticipant,
      _kind?: unknown,
      topic?: string,
    ): void => {
      if (topic !== CONFIRMATION_TOPIC) return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(new TextDecoder().decode(payload));
      } catch {
        return;
      }
      if (isConfirmationPendingPayload(parsed)) {
        onPending({
          confirmation_id: parsed.confirmation_id,
          action: parsed.action,
          description: parsed.description,
          type: parsed.confirmation_type ?? "tool",
          toolType: parsed.tool_type ?? undefined,
        });
        return;
      }
      if (isConfirmationClearedPayload(parsed)) {
        onCleared();
      }
    };

    room.on(RoomEvent.DataReceived, handler);
    return () => {
      room.off(RoomEvent.DataReceived, handler);
    };
  }, [room, onPending, onCleared]);
}
