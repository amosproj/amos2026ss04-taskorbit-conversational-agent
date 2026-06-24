/**
 * Subscribes to `taskorbit.force_commit` data-channel packets from the voice
 * worker and calls `onForceCommit` so the frontend can commit the current
 * utterance even when its own amplitude-based silence detection missed.
 *
 * The worker publishes this when the server-side Silero VAD detects the user
 * has stopped speaking (robust to background noise that holds the browser
 * analyser above its silence threshold, which would otherwise hang the turn).
 * #153.
 *
 * Must be used inside a `<LiveKitRoom>`.
 */

import { useRoomContext } from "@livekit/components-react";
import { RoomEvent, type RemoteParticipant } from "livekit-client";
import { useEffect } from "react";

const FORCE_COMMIT_TOPIC = "taskorbit.force_commit";

type ForceCommitPayload = { type: "force_commit" };

function isForceCommitPayload(value: unknown): value is ForceCommitPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { type?: unknown }).type === "force_commit"
  );
}

export function useForceCommit(onForceCommit: () => void): void {
  const room = useRoomContext();

  useEffect(() => {
    if (!room) return;

    const handler = (
      payload: Uint8Array,
      _participant?: RemoteParticipant,
      _kind?: unknown,
      topic?: string,
    ): void => {
      if (topic !== FORCE_COMMIT_TOPIC) return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(new TextDecoder().decode(payload));
      } catch {
        return;
      }
      if (!isForceCommitPayload(parsed)) return;
      onForceCommit();
    };

    room.on(RoomEvent.DataReceived, handler);
    return () => {
      room.off(RoomEvent.DataReceived, handler);
    };
  }, [room, onForceCommit]);
}
