import { useEffect, useState } from "react";

/**
 * Development sanity-check page.
 *
 * The actual conversational UI is the responsibility of issue #19
 * (frontend/design track). This component is intentionally minimal:
 * its job is to prove that the dev environment is wired correctly —
 * the backend is reachable, env vars are loaded, Tailwind compiles,
 * and the @ alias resolves.
 *
 * Replace this file freely as part of issue #19.
 */

type HealthState =
  | { status: "loading" }
  | { status: "ok"; service: string; version: string }
  | { status: "error"; message: string };

export function App() {
  const apiUrl = import.meta.env.VITE_API_URL ?? "";
  const livekitUrl = import.meta.env.VITE_LIVEKIT_URL ?? "";
  const appName = import.meta.env.VITE_APP_NAME ?? "TaskOrbit";

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

  return (
    <main className="min-h-svh bg-background text-foreground">
      <div className="mx-auto flex min-h-svh max-w-2xl flex-col justify-center gap-8 px-6 py-12">
        <header className="space-y-2">
          <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
            Development environment
          </p>
          <h1 className="text-4xl font-semibold tracking-tight">{appName}</h1>
          <p className="text-muted-foreground">
            Conversational agent — local dev sanity check.
          </p>
        </header>

        <section className="rounded-lg border border-border bg-card p-6 text-card-foreground">
          <h2 className="mb-4 text-sm font-semibold tracking-wide uppercase">
            Wiring check
          </h2>

          <dl className="space-y-3 text-sm">
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-muted-foreground">Backend</dt>
              <dd className="font-mono">
                {health.status === "loading" && "checking…"}
                {health.status === "ok" && (
                  <span className="text-green-600 dark:text-green-400">
                    ok · {health.service} v{health.version}
                  </span>
                )}
                {health.status === "error" && (
                  <span className="text-destructive">
                    unreachable · {health.message}
                  </span>
                )}
              </dd>
            </div>

            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-muted-foreground">VITE_API_URL</dt>
              <dd className="font-mono break-all">{apiUrl || "(unset)"}</dd>
            </div>

            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-muted-foreground">VITE_LIVEKIT_URL</dt>
              <dd className="font-mono break-all">{livekitUrl || "(unset)"}</dd>
            </div>
          </dl>
        </section>

        <footer className="text-xs text-muted-foreground">
          The conversational UI is built in issue&nbsp;#19. This page is
          a placeholder to verify the development environment.
        </footer>
      </div>
    </main>
  );
}
