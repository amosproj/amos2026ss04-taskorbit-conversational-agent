/**
 * Thin client for POST /api/v1/tts/synthesize.
 *
 * Fetches the MP3 audio stream for the given text and returns a temporary
 * object URL that can be passed to new Audio(url).play(). The caller must
 * call URL.revokeObjectURL(url) once playback is no longer needed to free
 * the memory.
 */
export async function synthesizeSpeech(
  text: string,
  signal?: AbortSignal,
): Promise<string> {
  const res = await fetch("/api/v1/tts/synthesize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }

  const blob = await res.blob();
  return URL.createObjectURL(blob);
}
