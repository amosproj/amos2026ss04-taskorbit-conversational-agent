/**
 * Bridges the LiveKit local participant's microphone publication to the
 * UI: enable/disable, audio-level data for the waveform, and a "commit
 * the current utterance" helper for the Send button.
 *
 * Must be used inside a `<LiveKitRoom>` — `useLocalParticipant` requires
 * the room context.
 *
 * Audio levels are sampled from a `WebAudio AnalyserNode` attached to the
 * published `MediaStreamTrack`. We poll on `requestAnimationFrame` and
 * keep the latest levels in a ref so the Waveform component can read
 * them without re-rendering this hook on every frame (which would
 * cascade re-renders into the whole call surface).
 */

import { useLocalParticipant } from "@livekit/components-react";
import { type LocalAudioTrack, LocalTrackPublication, Track } from "livekit-client";
import { useCallback, useEffect, useRef, useState } from "react";

const FFT_SIZE = 64;
const BAR_COUNT = FFT_SIZE / 2;

export type MicRecorderApi = {
  /** Whether the mic is currently publishing audio. */
  enabled: boolean;
  /** True between user gesture and the publication being live. */
  starting: boolean;
  /** The most recent permission/track error, if any. */
  error: string | null;
  /** A ref holding the latest 32 frequency-bin amplitudes (0–255). */
  levelsRef: React.MutableRefObject<Uint8Array>;
  /** Number of bars exposed in `levelsRef.current`. */
  barCount: number;
  /** Turn the mic on (publishes the local audio track). */
  enable: () => Promise<void>;
  /** Turn the mic off (unpublishes / mutes the local audio track). */
  disable: () => Promise<void>;
  /**
   * Commit the current utterance for processing.
   * In the streaming AgentSession architecture this just disables the
   * mic — the agent's VAD then detects end-of-turn and triggers the LLM.
   * Kept as a separate method so the UI semantics ("Send") survive any
   * future change in how we signal end-of-turn to the agent.
   */
  sendUtterance: () => Promise<void>;
  /**
   * Signal the agent worker to immediately stop TTS playback (button-triggered
   * barge-in). The backend calls session.interrupt() in response. Automatic
   * VAD barge-in runs independently via allow_interruptions=True on the backend.
   */
  sendInterrupt: () => Promise<void>;
};

export function useMicRecorder(): MicRecorderApi {
  const { localParticipant, microphoneTrack, isMicrophoneEnabled } = useLocalParticipant();

  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  // Reusable analyser context: avoid creating a new one on every
  // enable/disable cycle (Chromium silently caps the number of
  // AudioContexts a page may create).
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const levelsRef = useRef<Uint8Array>(new Uint8Array(BAR_COUNT));

  const stopAnalyser = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    try {
      sourceRef.current?.disconnect();
    } catch {
      // disconnect() throws if the node is already detached — safe to ignore.
    }
    sourceRef.current = null;
    levelsRef.current = new Uint8Array(BAR_COUNT);
  }, []);

  const startAnalyser = useCallback(
    (track: LocalAudioTrack) => {
      if (typeof window === "undefined") return;
      const mediaStreamTrack = track.mediaStreamTrack;
      if (!mediaStreamTrack) return;

      stopAnalyser();

      let ctx = audioCtxRef.current;
      if (!ctx) {
        ctx = new AudioContext();
        audioCtxRef.current = ctx;
      }
      if (ctx.state === "suspended") {
        // resume() is async but failures only mean the analyser stays
        // silent — the mic still publishes audio to LiveKit.
        void ctx.resume();
      }

      let analyser = analyserRef.current;
      if (!analyser) {
        analyser = ctx.createAnalyser();
        analyser.fftSize = FFT_SIZE;
        analyserRef.current = analyser;
      }

      const stream = new MediaStream([mediaStreamTrack]);
      const source = ctx.createMediaStreamSource(stream);
      source.connect(analyser);
      sourceRef.current = source;

      const buffer = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        if (!analyserRef.current) return;
        analyserRef.current.getByteFrequencyData(buffer);
        levelsRef.current = buffer.slice();
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    },
    [stopAnalyser],
  );

  // Keep the analyser tied to the published microphone track. When the
  // user toggles the mic the underlying MediaStreamTrack identity can
  // change, so we re-attach.
  useEffect(() => {
    if (!isMicrophoneEnabled) {
      stopAnalyser();
      return;
    }
    const pub = microphoneTrack;
    if (!(pub instanceof LocalTrackPublication)) return;
    const track = pub.audioTrack ?? (pub.track as LocalAudioTrack | undefined);
    if (!track) return;
    startAnalyser(track);
    return () => {
      stopAnalyser();
    };
  }, [isMicrophoneEnabled, microphoneTrack, startAnalyser, stopAnalyser]);

  // Tear down audio graph on unmount so we don't leak the AudioContext.
  useEffect(() => {
    return () => {
      stopAnalyser();
      try {
        analyserRef.current?.disconnect();
      } catch {
        /* ignore */
      }
      analyserRef.current = null;
      audioCtxRef.current?.close().catch(() => {
        // close() can reject if already closed; nothing actionable.
      });
      audioCtxRef.current = null;
    };
  }, [stopAnalyser]);

  const enable = useCallback(async () => {
    setError(null);
    setStarting(true);
    try {
      await localParticipant.setMicrophoneEnabled(true, {
        // Native browser noise processing reduces background noise reaching
        // both LiveKit and the AnalyserNode used for silence detection.
        noiseSuppression: true,
        echoCancellation: true,
        autoGainControl: true,
      });
    } catch (err) {
      const message = (err as Error).message || "Could not access microphone.";
      // Browsers report permission denial as NotAllowedError; the user
      // either rejected the prompt or has the device blocked at the OS.
      const name = (err as Error).name;
      if (name === "NotAllowedError" || /permission/i.test(message)) {
        setError("Microphone access was denied. Please allow microphone access to use voice.");
      } else {
        setError(message);
      }
      throw err;
    } finally {
      setStarting(false);
    }
  }, [localParticipant]);

  const disable = useCallback(async () => {
    try {
      // Capture the underlying track before unpublishing so we can stop
      // the hardware and remove the browser's "mic in use" indicator.
      const pub = localParticipant.getTrackPublication(Track.Source.Microphone);
      const msTrack = (pub?.track as LocalAudioTrack | undefined)?.mediaStreamTrack;

      await localParticipant.setMicrophoneEnabled(false);

      // Stop the raw MediaStreamTrack — this releases the hardware.
      // LiveKit will acquire a fresh track the next time enable() is called.
      msTrack?.stop();
    } catch (err) {
      // Disabling rarely fails (no permission required); still log via
      // state so the UI can react if it does.
      setError((err as Error).message || "Could not stop the microphone.");
    }
  }, [localParticipant]);

  const sendUtterance = useCallback(async () => {
    // Signal end-of-turn to the agent worker (maps to AgentSession.commit_user_turn)
    // so the reply starts without waiting for VAD silence. Then mute locally.
    const payload = new TextEncoder().encode(JSON.stringify({ type: "commit_turn" }));
    try {
      await localParticipant.publishData(payload, { reliable: true });
    } catch (err) {
      // First attempt failed — retry once to handle a transient data-channel glitch.
      console.error("[useMicRecorder] publishData commit_turn failed, retrying:", err);
      try {
        await localParticipant.publishData(payload, { reliable: true });
      } catch (retryErr) {
        // Both attempts failed; the agent will rely on VAD endpointing instead.
        console.error("[useMicRecorder] publishData commit_turn retry also failed:", retryErr);
      }
    }
    await disable();
  }, [disable, localParticipant]);

  const sendInterrupt = useCallback(async () => {
    const payload = new TextEncoder().encode(JSON.stringify({ type: "interrupt_playback" }));
    try {
      await localParticipant.publishData(payload, { reliable: true });
    } catch {
      // Best-effort — VAD barge-in on the backend is the primary mechanism.
    }
  }, [localParticipant]);

  // Snapshot the published-state into a stable variable so the public
  // surface doesn't change identity unless the underlying value does.
  const enabled =
    isMicrophoneEnabled &&
    microphoneTrack instanceof LocalTrackPublication &&
    !microphoneTrack.isMuted;

  // Track.Source.Microphone is exported for ergonomics — even though we
  // don't pass it anywhere here, downstream tests/components may want to
  // identify the same track via the participant API.
  void Track.Source.Microphone;

  return {
    enabled,
    starting,
    error,
    levelsRef,
    barCount: BAR_COUNT,
    enable,
    disable,
    sendUtterance,
    sendInterrupt,
  };
}
