/**
 * Client for POST /api/v1/tts/synthesize (ElevenLabs MP3).
 *
 * `synthesizeSpeech` returns a temporary object URL. `playSynthesizedSpeech`
 * fetches, plays via HTMLAudioElement, and revokes the URL — use it for
 * read-aloud of assistant replies on the text-input path (voice mode still
 * uses LiveKit / RoomAudioRenderer for agent TTS).
 */

export type SynthesizeOptions = {
  signal?: AbortSignal;
  voiceId?: string;
  modelId?: string;
};

export async function synthesizeSpeech(
  text: string,
  options?: SynthesizeOptions,
): Promise<string> {
  const { signal, voiceId, modelId } = options ?? {};
  const body: Record<string, unknown> = { text };
  if (voiceId) body.voice_id = voiceId;
  if (modelId) body.model_id = modelId;

  const res = await fetch("/api/v1/tts/synthesize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }

  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

/**
 * Fetch MP3 for `text`, play to completion, then revoke the blob URL.
 * No-ops on empty text. Re-throws synthesize/playback errors (caller can ignore).
 */
export async function playSynthesizedSpeech(
  text: string,
  options?: SynthesizeOptions,
): Promise<void> {
  const trimmed = text.trim();
  if (!trimmed) return;

  const url = await synthesizeSpeech(trimmed, options);
  try {
    await playAudioUrl(url, options?.signal);
  } finally {
    URL.revokeObjectURL(url);
  }
}

function playAudioUrl(url: string, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const audio = new Audio(url);
    const cleanup = () => {
      signal?.removeEventListener("abort", onAbort);
    };
    const onAbort = () => {
      audio.pause();
      cleanup();
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort);
    audio.onended = () => {
      cleanup();
      resolve();
    };
    audio.onerror = () => {
      cleanup();
      reject(new Error("Audio playback failed"));
    };
    void audio.play().catch((e) => {
      cleanup();
      reject(e instanceof Error ? e : new Error(String(e)));
    });
  });
}
