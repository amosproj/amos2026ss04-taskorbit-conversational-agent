import { useState } from "react";
import { ChevronDown } from "lucide-react";

import { useBackendHealth } from "@/hooks/useBackendHealth";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type CheckTone = "ok" | "warn" | "error" | "loading";

type Check = {
  label: string;
  tone: CheckTone;
  detail: string;
};

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
export function PreCallDiagnostics() {
  const { health, apiUrl } = useBackendHealth();
  const livekitUrl = import.meta.env.VITE_LIVEKIT_URL ?? "";
  const [showDetail, setShowDetail] = useState(false);

  const backendCheck: Check =
    health.status === "loading"
      ? { label: "Backend", tone: "loading", detail: "Checking /health…" }
      : health.status === "ok"
        ? {
            label: "Backend",
            tone: "ok",
            detail: `${health.service} v${health.version}`,
          }
        : {
            label: "Backend",
            tone: "error",
            detail: `unreachable · ${health.message}`,
          };

  const livekitCheck: Check = livekitUrl
    ? { label: "LiveKit", tone: "ok", detail: livekitUrl }
    : {
        label: "LiveKit",
        tone: "warn",
        detail: "VITE_LIVEKIT_URL is not set — voice will not connect.",
      };

  const checks: Check[] = [backendCheck, livekitCheck];
  const hasIssue = checks.some((c) => c.tone === "error" || c.tone === "warn");

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 py-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {checks.map((check) => (
            <div key={check.label} className="flex items-center gap-2 text-sm">
              <span
                aria-hidden
                className={cn(
                  "inline-block size-2.5 rounded-full",
                  toneClasses[check.tone],
                )}
              />
              <span className="font-medium">{check.label}</span>
              <span className="text-muted-foreground">
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
          <button
            type="button"
            onClick={() => setShowDetail((v) => !v)}
            className={cn(
              "ml-auto flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground",
              hasIssue && "text-foreground",
            )}
            aria-expanded={showDetail}
          >
            {showDetail ? "Hide" : "Show"} technical info
            <ChevronDown
              aria-hidden
              className={cn(
                "size-3 transition-transform",
                showDetail && "rotate-180",
              )}
            />
          </button>
        </div>
        {showDetail ? (
          <dl className="grid grid-cols-1 gap-2 border-t pt-3 text-xs sm:grid-cols-[8rem_minmax(0,1fr)]">
            {checks.map((check) => (
              <div
                key={`${check.label}-detail`}
                className="contents text-muted-foreground"
              >
                <dt className="font-medium">{check.label}</dt>
                <dd className="font-mono break-all">{check.detail}</dd>
              </div>
            ))}
            <dt className="font-medium text-muted-foreground">VITE_API_URL</dt>
            <dd className="font-mono break-all text-muted-foreground">
              {apiUrl || "(using Vite /api proxy)"}
            </dd>
            <dt className="font-medium text-muted-foreground">
              VITE_LIVEKIT_URL
            </dt>
            <dd className="font-mono break-all text-muted-foreground">
              {livekitUrl || "(unset)"}
            </dd>
          </dl>
        ) : null}
      </CardContent>
    </Card>
  );
}
