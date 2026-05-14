import { useEffect, useRef } from "react";

const POLL_MS = 100;
const SILENCE_DURATION_MS = 2000;
const SILENCE_THRESHOLD = 20; // 0–255 average amplitude; raised to ignore typical background noise

/**
 * Fires `onSilence` once when the audio levels in `levelsRef` stay below
 * SILENCE_THRESHOLD for SILENCE_DURATION_MS while `active` is true.
 *
 * Used as a frontend safety net: if the user stops speaking for 2 seconds
 * while the mic is open, the turn is auto-submitted without requiring the
 * Send button.
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

    let silenceStart: number | null = null;
    let fired = false;

    const id = setInterval(() => {
      if (fired) return;

      const levels = levelsRef.current;
      const avg = levels.reduce((s, v) => s + v, 0) / (levels.length || 1);

      if (avg < SILENCE_THRESHOLD) {
        if (silenceStart === null) {
          silenceStart = Date.now();
        } else if (Date.now() - silenceStart >= SILENCE_DURATION_MS) {
          fired = true;
          onSilenceRef.current();
        }
      } else {
        silenceStart = null; // speech detected — reset silence timer
      }
    }, POLL_MS);

    return () => clearInterval(id);
  }, [active, levelsRef]);
}
