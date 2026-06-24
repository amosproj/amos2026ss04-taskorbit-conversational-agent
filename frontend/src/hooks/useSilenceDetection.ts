import { useEffect, useRef } from "react";

const POLL_MS = 100;
// Tuned for #153: SILENCE_THRESHOLD raised 20→26 and SILENCE_DURATION_MS lowered
// 2000→1500 to shrink the gray zone (20–29 amplitude) where ambient room noise
// was resetting the silence timer before it could fire.
const SILENCE_DURATION_MS = 1500;
const SILENCE_THRESHOLD = 26; // 0–255; below this is considered silence
const SPEECH_THRESHOLD = 30; // 0–255; must cross this before silence detection arms

/**
 * Fires `onSilence` once when the user STOPS speaking — specifically, when
 * audio levels drop below SILENCE_THRESHOLD for SILENCE_DURATION_MS, but
 * only AFTER the user has actually spoken (amplitude crossed SPEECH_THRESHOLD
 * at least once during the current active window).
 *
 * This prevents the hook from auto-submitting on ambient silence when the mic
 * opens but the user hasn't said anything yet, which would cause an infinite
 * request loop in continuous voice mode.
 */
export function useSilenceDetection({
  levelsRef,
  active,
  onSilence,
}: {
  levelsRef: React.MutableRefObject<Uint8Array>;
  active: boolean;
  onSilence: () => void;
}) {
  // Keep latest callback in a ref so the interval closure never goes stale.
  const onSilenceRef = useRef(onSilence);
  useEffect(() => {
    onSilenceRef.current = onSilence;
  }, [onSilence]);

  useEffect(() => {
    if (!active) return;

    let hasSpeech = false; // armed only after real speech is detected
    let silenceStart: number | null = null;
    let fired = false;

    const id = setInterval(() => {
      if (fired) return;

      const levels = levelsRef.current;
      const avg = levels.reduce((s, v) => s + v, 0) / (levels.length || 1);

      if (avg >= SPEECH_THRESHOLD) {
        hasSpeech = true;
        silenceStart = null; // speech detected — reset silence timer
        return;
      }

      // Below silence threshold — only start counting if user already spoke.
      if (!hasSpeech) return;

      if (avg < SILENCE_THRESHOLD) {
        if (silenceStart === null) {
          silenceStart = Date.now();
        } else if (Date.now() - silenceStart >= SILENCE_DURATION_MS) {
          fired = true;
          onSilenceRef.current();
        }
      } else {
        silenceStart = null;
      }
    }, POLL_MS);

    return () => clearInterval(id);
  }, [active, levelsRef]);
}
