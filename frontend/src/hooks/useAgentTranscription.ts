/**
 * Subscribes to live transcription text streams from the LiveKit room
 * and forwards each segment to a caller-supplied callback. Both the
 * user's STT segments and the agent's TTS-aligned transcription arrive
 * on the same `lk.transcription` topic, distinguishable by the sender
 * identity.
 *
 * The hook is callback-based rather than returning state so the parent
 * (`useVoiceCall`) can decide how to merge interim updates with its
 * existing transcript array. We never own transcript state here.
 *
 * Must be used inside a `<LiveKitRoom>`.
 */

import { useRoomContext } from "@livekit/components-react";
import { useEffect } from "react";

const TRANSCRIPTION_TOPIC = "lk.transcription";

export type TranscriptionSegment = {
  /** Stable across interim and final updates of the same utterance. */
  id: string;
  role: "user" | "assistant";
  text: string;
  isFinal: boolean;
};

export type TranscriptionHandler = (segment: TranscriptionSegment) => void;

export function useAgentTranscription(onSegment: TranscriptionHandler): void {
  const room = useRoomContext();

  useEffect(() => {
    if (!room) return;

    const handler = async (
      reader: {
        info: { attributes?: Record<string, string>; id?: string };
        readAll: () => Promise<string>;
      },
      participant: { identity: string },
    ): Promise<void> => {
      try {
        const text = await reader.readAll();
        const attrs = reader.info.attributes ?? {};
        // The agent worker stamps `lk.transcribed_track_id` only on
        // transcription streams (vs other text streams that share the
        // topic accidentally). Treat absence as a non-transcription.
        if (!attrs["lk.transcribed_track_id"]) return;

        const isFinal = attrs["lk.transcription_final"] === "true";
        const segmentId =
          attrs["lk.segment_id"] ?? reader.info.id ?? `seg-${Date.now()}`;
        const role: "user" | "assistant" =
          participant.identity === room.localParticipant.identity
            ? "user"
            : "assistant";

        onSegment({ id: segmentId, role, text, isFinal });
      } catch (err) {
        // Don't break the room over a single malformed stream — just
        // log and let subsequent streams flow.
        // eslint-disable-next-line no-console
        console.warn("[useAgentTranscription] failed to read stream", err);
      }
    };

    // Cast through unknown — registerTextStreamHandler types vary across
    // livekit-client minor versions, but the runtime contract is stable.
    const register = room.registerTextStreamHandler.bind(room) as (
      topic: string,
      cb: typeof handler,
    ) => void;
    const unregister = (
      room as unknown as {
        unregisterTextStreamHandler?: (topic: string) => void;
      }
    ).unregisterTextStreamHandler?.bind(room);

    register(TRANSCRIPTION_TOPIC, handler);

    return () => {
      try {
        unregister?.(TRANSCRIPTION_TOPIC);
      } catch {
        // Older livekit-client versions raise on duplicate unregister;
        // safe to swallow because the handler is local to this hook.
      }
    };
  }, [room, onSegment]);
}
