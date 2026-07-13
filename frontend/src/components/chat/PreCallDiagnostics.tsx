import { useState } from "react";
import { ChevronDown } from "lucide-react";

import { useBackendHealth, type HealthState } from "@/hooks/useBackendHealth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type CheckTone = "ok" | "warn" | "error" | "loading";

type Check = {
  label: string;
  tone: CheckTone;
  detail: string;
};

type HealthOk = Extract<HealthState, { status: "ok" }>;

/** Derives a traffic-light Check from the shared /health polling state. */
function checkFromHealth(
  health: HealthState,
  label: string,
  render: {
    loading: string;
    ok: (h: HealthOk) => Pick<Check, "tone" | "detail">;
    error: (message: string) => string;
  },
): Check {
  if (health.status === "loading") return { label, tone: "loading", detail: render.loading };
  if (health.status === "error")
    return { label, tone: "error", detail: render.error(health.message) };
  return { label, ...render.ok(health) };
}

const toneClasses: Record<CheckTone, string> = {
  ok: "bg-primary",
  warn: "bg-muted-foreground",
  error: "bg-destructive",
  loading: "bg-muted-foreground/60 animate-pulse",
};

/**
 * Pre-call traffic-light strip. Surfaces the same connectivity signals
 * Shikhar's original "Development wiring" card showed, but framed as
 * actionable readiness checks rather than a developer panel. The full
 * technical detail (env-var values, error messages) lives behind the
 * disclosure so it's available without dominating the surface.
 */
export function PreCallDiagnostics({ className }: { className?: string }) {
  const { health } = useBackendHealth();
  const apiUrl = import.meta.env.VITE_API_URL ?? "";
  const [showDetail, setShowDetail] = useState(false);

  const backendCheck = checkFromHealth(health, "Backend", {
    loading: "Checking /health…",
    ok: (h) => ({ tone: "ok", detail: `${h.service} v${h.version}` }),
    error: (message) => `unreachable · ${message}`,
  });

  // LiveKit URL/credentials live only in backend Settings and are handed to the
  // frontend per-session via POST /v1/livekit/token — there is no frontend env
  // var to check. The backend reports whether it's configured via /health.
  const livekitCheck = checkFromHealth(health, "LiveKit", {
    loading: "Checking backend config…",
    ok: (h) =>
      h.livekit_configured
        ? { tone: "ok", detail: "Configured on backend" }
        : {
            tone: "warn",
            detail: "LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET not set on backend.",
          },
    error: () => "Cannot verify — backend unreachable.",
  });

  const checks: Check[] = [backendCheck, livekitCheck];
  const hasIssue = checks.some((c) => c.tone === "error" || c.tone === "warn");

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>System</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-2">
          {checks.map((check) => (
            <div key={check.label} className="flex items-center gap-2 text-sm">
              <span
                aria-hidden
                className={cn(
                  "inline-block size-2.5 shrink-0 rounded-full",
                  toneClasses[check.tone],
                )}
              />
              <span className="font-medium">{check.label}</span>
              <span className="ml-auto text-muted-foreground">
                {check.tone === "ok"
                  ? "ready"
                  : check.tone === "loading"
                    ? "checking"
                    : check.tone === "warn"
                      ? "not configured"
                      : "unreachable"}
              </span>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setShowDetail((v) => !v)}
          className={cn(
            "flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground",
            hasIssue && "text-foreground",
          )}
          aria-expanded={showDetail}
        >
          {showDetail ? "Hide" : "Show"} technical info
          <ChevronDown
            aria-hidden
            className={cn("size-3 transition-transform", showDetail && "rotate-180")}
          />
        </button>
        {showDetail ? (
          <dl className="grid grid-cols-1 gap-2 border-t pt-3 text-xs sm:grid-cols-[8rem_minmax(0,1fr)]">
            {checks.map((check) => (
              <div key={`${check.label}-detail`} className="contents text-muted-foreground">
                <dt className="font-medium">{check.label}</dt>
                <dd className="font-mono break-all">{check.detail}</dd>
              </div>
            ))}
            <dt className="font-medium text-muted-foreground">VITE_API_URL</dt>
            <dd className="font-mono break-all text-muted-foreground">
              {apiUrl || "(using Vite /api proxy)"}
            </dd>
          </dl>
        ) : null}
      </CardContent>
    </Card>
  );
}
