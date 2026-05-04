/**
 * Thin client for POST /api/v1/livekit/token.
 *
 * Asks the FastAPI backend to mint a short-lived LiveKit access token for
 * the given identity / room. The backend response also includes the
 * LiveKit Cloud URL the frontend should pass to `livekit-client`'s
 * `Room.connect(url, token)`. The Vite dev server proxies `/api/*` to the
 * backend (see `frontend/vite.config.ts`), so this works without CORS
 * configuration in development.
 *
 * Implements ticket #26 (LiveKit Cloud infrastructure). The actual room
 * connection / publish flow lives with the voice tickets (#14, #15).
 */

export type LiveKitTokenResponse = {
  token: string;
  url: string;
  room: string;
  identity: string;
};

/**
 * Request a LiveKit access token from the backend.
 *
 * @param identity - Stable participant identity (e.g. user id or `"dev-user"`)
 * @param room     - LiveKit room name to join
 * @param signal   - Optional AbortSignal to cancel the in-flight request
 * @throws Error with the backend's `detail` message when the response is non-2xx.
 */
export async function fetchLiveKitToken(
  identity: string,
  room: string,
  signal?: AbortSignal,
): Promise<LiveKitTokenResponse> {
  const res = await fetch("/api/v1/livekit/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identity, room }),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }

  return (await res.json()) as LiveKitTokenResponse;
}
