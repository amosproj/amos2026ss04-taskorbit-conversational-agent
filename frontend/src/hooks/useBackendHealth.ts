import { useEffect, useState } from "react";

export type HealthState =
  | { status: "loading" }
  | { status: "ok"; service: string; version: string }
  | { status: "error"; message: string };

const HEALTH_URL = "/api/health";
const MAX_ATTEMPTS = 5;
const BASE_DELAY_MS = 500;

/**
 * Probes the FastAPI `/health` endpoint with exponential backoff.
 *
 * Under `docker compose up` the frontend often finishes booting before
 * the backend is ready, which manifests as a Vite proxy `ECONNREFUSED`.
 * Retrying gives the UI a chance to recover without a manual refresh,
 * while stopping after the first success keeps the dev logs quiet.
 */
export function useBackendHealth() {
  const [health, setHealth] = useState<HealthState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    let cancelled = false;

    const attempt = async (n: number): Promise<void> => {
      try {
        const res = await fetch(HEALTH_URL, { signal: controller.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as { service: string; version: string };
        if (!cancelled) setHealth({ status: "ok", ...body });
      } catch (err) {
        const error = err as Error;
        if (cancelled || error.name === "AbortError") return;
        if (n >= MAX_ATTEMPTS - 1) {
          setHealth({ status: "error", message: error.message });
          return;
        }
        // 0.5s, 1s, 2s, 4s, then give up.
        const delay = BASE_DELAY_MS * 2 ** n;
        timer = window.setTimeout(() => void attempt(n + 1), delay);
      }
    };

    void attempt(0);

    return () => {
      cancelled = true;
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  return { health };
}
