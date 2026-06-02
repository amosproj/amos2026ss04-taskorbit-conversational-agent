/**
 * Subscribes to `taskorbit.agent_routed` data-channel packets from the
 * voice worker and calls `onRouted` with the snake_case agent name
 * (e.g. "technical_support") after each conversation turn.
 *
 * Must be used inside a `<LiveKitRoom>`.
 */

import { useRoomContext } from "@livekit/components-react";
import { RoomEvent, type RemoteParticipant } from "livekit-client";
import { useEffect } from "react";

const ROUTED_AGENT_TOPIC = "taskorbit.agent_routed";

type RoutedPayload = { type: "agent_routed"; agent: string };

function isRoutedPayload(value: unknown): value is RoutedPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { type?: unknown }).type === "agent_routed" &&
    typeof (value as { agent?: unknown }).agent === "string"
  );
}

export function useRoutedAgent(onRouted: (agentName: string) => void): void {
  const room = useRoomContext();

  useEffect(() => {
    if (!room) return;

    const handler = (
      payload: Uint8Array,
      _participant?: RemoteParticipant,
      _kind?: unknown,
      topic?: string,
    ): void => {
      if (topic !== ROUTED_AGENT_TOPIC) return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(new TextDecoder().decode(payload));
      } catch {
        return;
      }
      if (!isRoutedPayload(parsed)) return;
      onRouted(parsed.agent);
    };

    room.on(RoomEvent.DataReceived, handler);
    return () => {
      room.off(RoomEvent.DataReceived, handler);
    };
  }, [room, onRouted]);
}
