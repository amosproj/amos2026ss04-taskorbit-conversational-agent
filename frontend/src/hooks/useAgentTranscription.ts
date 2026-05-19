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
import { type TextStreamReader } from "livekit-client";
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
      reader: TextStreamReader,
      participant: { identity: string },
    ): Promise<void> => {
      try {
        const attrs = reader.info.attributes ?? {};
        // The agent worker stamps `lk.transcribed_track_id` only on
        // transcription streams (vs other text streams that share the
        // topic accidentally). Treat absence as a non-transcription.
        if (!attrs["lk.transcribed_track_id"]) return;

        const segmentId = attrs["lk.segment_id"] ?? reader.info.id ?? `seg-${Date.now()}`;
        const role: "user" | "assistant" =
          participant.identity === room.localParticipant.identity ? "user" : "assistant";

        // STT (user) and TTS (assistant) send different stream formats:
        //   STT — Deepgram writes full partial transcripts that grow each time
        //         ("Hi" → "Hi there" → "Hi there how"). Take the latest chunk.
        //   TTS — livekit-agents writes one word at a time with sync_transcription=True.
        //         Concatenate to build the sentence progressively.
        let latest = "";
        let accumulated = "";
        for await (const chunk of reader) {
          if (role === "user") {
            latest = chunk;
            onSegment({ id: segmentId, role, text: latest.trim(), isFinal: false });
          } else {
            accumulated += chunk;
            onSegment({ id: segmentId, role, text: accumulated.trim(), isFinal: false });
          }
        }
        const finalText = (role === "user" ? latest : accumulated).trim();
        if (finalText) {
          onSegment({ id: segmentId, role, text: finalText, isFinal: true });
        }
      } catch (err) {
        // Don't break the room over a single malformed stream — just
        // log and let subsequent streams flow.
        console.warn("[useAgentTranscription] failed to read stream", err);
      }
    };

    const unregister = (
      room as unknown as {
        unregisterTextStreamHandler?: (topic: string) => void;
      }
    ).unregisterTextStreamHandler?.bind(room);

    room.registerTextStreamHandler(TRANSCRIPTION_TOPIC, handler);

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
