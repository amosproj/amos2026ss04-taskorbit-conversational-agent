/**
 * Subscribes to `taskorbit.session_ended` data-channel packets from the
 * voice worker and calls `onEnded` so the frontend can tear down the call.
 *
 * The worker publishes this after the orchestrator returns status="ended"
 * (e.g. when the user says "goodbye" and the agent has an end_call tool).
 *
 * Must be used inside a `<LiveKitRoom>`.
 */

import { useRoomContext } from "@livekit/components-react";
import { RoomEvent, type RemoteParticipant } from "livekit-client";
import { useEffect } from "react";

const SESSION_ENDED_TOPIC = "taskorbit.session_ended";

type SessionEndedPayload = { type: "session_ended" };

function isSessionEndedPayload(value: unknown): value is SessionEndedPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { type?: unknown }).type === "session_ended"
  );
}

export function useSessionEnded(onEnded: () => void): void {
  const room = useRoomContext();

  useEffect(() => {
    if (!room) return;

    const handler = (
      payload: Uint8Array,
      _participant?: RemoteParticipant,
      _kind?: unknown,
      topic?: string,
    ): void => {
      if (topic !== SESSION_ENDED_TOPIC) return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(new TextDecoder().decode(payload));
      } catch {
        return;
      }
      if (!isSessionEndedPayload(parsed)) return;
      onEnded();
    };

    room.on(RoomEvent.DataReceived, handler);
    return () => {
      room.off(RoomEvent.DataReceived, handler);
    };
  }, [room, onEnded]);
}
