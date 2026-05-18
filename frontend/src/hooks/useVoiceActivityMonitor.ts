/**
 * Passively monitors microphone amplitude without publishing audio to LiveKit.
 * Fires `onSpeech()` once per activation when sustained speech is detected,
 * enabling automatic barge-in during the agent's `speaking` phase.
 *
 * A separate getUserMedia stream is used so the mic remains unpublished
 * (no LiveKit track, no network cost). echoCancellation filters out the
 * agent's own TTS audio coming through the speakers, preventing false triggers.
 *
 * Detection is intentionally conservative:
 *   - Amplitude must exceed SPEECH_THRESHOLD (above typical ambient noise)
 *   - Speech must be sustained for SPEECH_SUSTAIN_MS (rejects coughs/clicks)
 *
 * If mic access is denied, the hook silently no-ops — the backend VAD
 * (allow_interruptions=True, min_interruption_duration=0.5 s) acts as fallback.
 */

import { useEffect, useRef } from "react";

// Amplitude threshold (0–255). 55 rejects typical ambient noise (~10–25) and
// brief background sounds (~30–45), requiring clear conversational speech (~60–120).
const SPEECH_THRESHOLD = 55;

// Sustained duration before onSpeech fires. 500 ms rejects coughs, clicks, and
// short background bursts that rarely exceed 300 ms, while still feeling
// responsive for intentional speech.
const SPEECH_SUSTAIN_MS = 1000;

// Poll interval. 50 ms gives ≤350 ms total detection latency (sustain + 1 poll).
const POLL_MS = 50;

// Analyser bin range covering ~300 Hz – 3 kHz (speech fundamentals + formants).
// At a 44.1 kHz sample rate with fftSize=256, each bin spans ~344 Hz;
// bins 1–9 cover the range. Use a slightly wider 2–40 window for robustness
// across sample rates (48 kHz is common in browsers).
const BIN_START = 2;
const BIN_END = 40;

type Options = {
  /** Activate monitoring. When false, any open stream is released. */
  active: boolean;
  /** Called exactly once per activation window when speech is detected. */
  onSpeech: () => void;
  /** Override amplitude threshold (0–255). Defaults to SPEECH_THRESHOLD. */
  threshold?: number;
  /** Override sustain duration in ms. Defaults to SPEECH_SUSTAIN_MS. */
  sustainMs?: number;
};

export function useVoiceActivityMonitor({
  active,
  onSpeech,
  threshold = SPEECH_THRESHOLD,
  sustainMs = SPEECH_SUSTAIN_MS,
}: Options): void {
  // Stable ref so the interval closure always sees the latest callback without
  // restarting the entire effect when the parent re-renders.
  const onSpeechRef = useRef(onSpeech);
  onSpeechRef.current = onSpeech;

  useEffect(() => {
    if (!active) return;

    let stream: MediaStream | null = null;
    let audioCtx: AudioContext | null = null;
    let analyser: AnalyserNode | null = null;
    let intervalId: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;

    let speechStartTs = 0;
    let fired = false;

    const stop = () => {
      if (intervalId !== null) clearInterval(intervalId);
      if (stream) stream.getTracks().forEach((t) => t.stop());
      try {
        audioCtx?.close();
      } catch {
        /* ignore */
      }
      stream = null;
      audioCtx = null;
      analyser = null;
      intervalId = null;
    };

    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            // Disable AGC so amplitude values remain proportional to actual
            // voice volume — AGC would inflate quiet sounds past the threshold.
            autoGainControl: false,
          },
          video: false,
        });
      } catch {
        // Mic access denied or unavailable — backend VAD handles barge-in.
        return;
      }

      if (cancelled) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }

      audioCtx = new AudioContext();
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      audioCtx.createMediaStreamSource(stream).connect(analyser);

      const bins = new Uint8Array(analyser.frequencyBinCount);
      const end = Math.min(BIN_END, analyser.frequencyBinCount - 1);

      intervalId = setInterval(() => {
        if (!analyser || fired) return;

        analyser.getByteFrequencyData(bins);

        let sum = 0;
        const count = end - BIN_START + 1;
        for (let i = BIN_START; i <= end; i++) sum += bins[i] ?? 0;
        const avg = sum / count;

        if (avg >= threshold) {
          if (speechStartTs === 0) speechStartTs = Date.now();
          if (Date.now() - speechStartTs >= sustainMs) {
            fired = true;
            onSpeechRef.current();
            stop();
          }
        } else {
          speechStartTs = 0;
        }
      }, POLL_MS);
    })();

    return () => {
      cancelled = true;
      stop();
    };
  }, [active, threshold, sustainMs]);
}
