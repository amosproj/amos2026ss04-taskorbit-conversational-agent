import { useEffect, useState } from "react";

export type HealthState =
  | { status: "loading" }
  | { status: "ok"; service: string; version: string }
  | { status: "error"; message: string };

/**
 * Fetches the FastAPI `/health` check used by the dev environment (#17)
 * to verify the backend is reachable. Safe to use while the real agent
 * UI is still mocked (#5).
 */
export function useBackendHealth() {
  const apiUrl = import.meta.env.VITE_API_URL ?? "";

  const [health, setHealth] = useState<HealthState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    const url = apiUrl ? `${apiUrl}/health` : "/api/health";

    fetch(url, { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<{ service: string; version: string }>;
      })
      .then((body) => setHealth({ status: "ok", ...body }))
      .catch((err: Error) => {
        if (err.name === "AbortError") return;
        setHealth({ status: "error", message: err.message });
      });

    return () => controller.abort();
  }, [apiUrl]);

  return { health, apiUrl };
}
