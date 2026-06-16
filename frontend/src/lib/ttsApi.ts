/**
 * Client for POST /api/v1/tts/synthesize (ElevenLabs MP3).
 *
 * `synthesizeSpeech` returns a temporary object URL. `playSynthesizedSpeech`
 * fetches, plays via HTMLAudioElement, and revokes the URL — use it for
 * read-aloud of assistant replies on the text-input path (voice mode still
 * uses LiveKit / RoomAudioRenderer for agent TTS).
 *
 * `playWithWordSync` uses the /synthesize-with-timestamps endpoint to drive
 * a callback at each word's exact audio timestamp, making static TTS (e.g.
 * the greeting) word-synchronized the same way LiveKit streaming turns are.
 */

export type SynthesizeOptions = {
  signal?: AbortSignal;
  voiceId?: string;
  modelId?: string;
  /** When provided, the Audio element's volume is synced to this ref every 50 ms. */
  volumeRef?: { current: number };
};

export async function synthesizeSpeech(text: string, options?: SynthesizeOptions): Promise<string> {
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
    await playAudioUrl(url, options?.signal, options?.volumeRef);
  } finally {
    URL.revokeObjectURL(url);
  }
}

type WordTimestamp = { word: string; start_time: number; end_time: number };

type WithTimestampsResponse = {
  audio_base64: string;
  word_timestamps: WordTimestamp[];
};

/**
 * Fetch audio + word timestamps, play the audio, and call `onWord` at each
 * word's exact start time. `onWord` receives the partial sentence built so
 * far so the caller can update transcript state identically to how the
 * LiveKit stream drives agent responses.
 *
 * Falls back to plain `playSynthesizedSpeech` if the timestamps endpoint
 * fails, so the greeting is always spoken even without timing data.
 */
export async function playWithWordSync(
  text: string,
  options: SynthesizeOptions & { onWord: (partialText: string, isFinal: boolean) => void },
): Promise<void> {
  const { signal, voiceId, modelId, onWord } = options;
  const trimmed = text.trim();
  if (!trimmed) return;

  const body: Record<string, unknown> = { text: trimmed };
  if (voiceId) body.voice_id = voiceId;
  if (modelId) body.model_id = modelId;

  let data: WithTimestampsResponse;
  try {
    const res = await fetch("/api/v1/tts/synthesize-with-timestamps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = (await res.json()) as WithTimestampsResponse;
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    // Timestamps endpoint unavailable — fall back to plain TTS with no sync.
    console.warn("[ttsApi] timestamps fetch failed, falling back", err);
    await playSynthesizedSpeech(trimmed, { signal, voiceId, modelId });
    onWord(trimmed, true);
    return;
  }

  // Convert base64 audio to a playable blob URL.
  const audioBytes = Uint8Array.from(atob(data.audio_base64), (c) => c.charCodeAt(0));
  const blob = new Blob([audioBytes], { type: "audio/mpeg" });
  const url = URL.createObjectURL(blob);

  const timers: ReturnType<typeof setTimeout>[] = [];
  const words = data.word_timestamps;

  // Schedule each word reveal at its exact spoken timestamp.
  words.forEach((w, i) => {
    const isLast = i === words.length - 1;
    const partial = words
      .slice(0, i + 1)
      .map((t) => t.word)
      .join(" ");
    timers.push(
      setTimeout(() => {
        onWord(partial, isLast);
      }, w.start_time * 1000),
    );
  });

  // Cancel pending word timers if the signal aborts mid-playback.
  const onAbort = () => timers.forEach(clearTimeout);
  signal?.addEventListener("abort", onAbort, { once: true });

  try {
    await playAudioUrl(url, signal, options?.volumeRef);
  } finally {
    signal?.removeEventListener("abort", onAbort);
    URL.revokeObjectURL(url);
  }
}

function playAudioUrl(
  url: string,
  signal?: AbortSignal,
  volumeRef?: { current: number },
): Promise<void> {
  return new Promise((resolve, reject) => {
    const audio = new Audio(url);
    if (volumeRef !== undefined) {
      audio.volume = Math.max(0, Math.min(1, volumeRef.current));
    }
    // Poll the ref so mute changes take effect within 50 ms while already playing.
    const pollId =
      volumeRef !== undefined
        ? setInterval(() => {
            audio.volume = Math.max(0, Math.min(1, volumeRef.current));
          }, 50)
        : undefined;
    const cleanup = () => {
      if (pollId !== undefined) clearInterval(pollId);
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
