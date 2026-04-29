import { Loader2, ShieldCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import type { CallStatus } from "@/types/callState";

type Props = {
  status: CallStatus;
  agentName: string;
  className?: string;
};

type Visual =
  | { kind: "icon"; Icon: LucideIcon; spin: boolean; label: string }
  | { kind: "pulse"; label: string }
  | { kind: "speaking"; label: string };

function visualFor(status: CallStatus, agentName: string): Visual | null {
  switch (status) {
    case "connecting":
      return { kind: "icon", Icon: Loader2, spin: true, label: "Connecting…" };
    case "listening":
      return { kind: "pulse", label: "Listening" };
    case "thinking":
      return {
        kind: "icon",
        Icon: Loader2,
        spin: true,
        label: `${agentName} is thinking…`,
      };
    case "speaking":
      return { kind: "speaking", label: `${agentName} is speaking` };
    case "awaiting_confirmation":
      return {
        kind: "icon",
        Icon: ShieldCheck,
        spin: false,
        label: "Waiting for your approval",
      };
    case "idle":
    case "ended":
      return null;
  }
}

/**
 * Tells the user — and reviewers — what the call surface is doing right
 * now. The visual differs per phase: spinner for connecting/thinking,
 * pulsing dot for listening, animated bars for speaking, shield for the
 * confirmation pause. Hidden in idle/ended states (the surrounding UI
 * already communicates those).
 */
export function CallStatusIndicator({ status, agentName, className }: Props) {
  const visual = visualFor(status, agentName);
  if (visual === null) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex items-center gap-2 rounded-full border bg-card px-3 py-1.5 text-sm",
        className,
      )}
    >
      {visual.kind === "icon" ? (
        <visual.Icon
          aria-hidden
          className={cn("size-4", visual.spin && "animate-spin")}
        />
      ) : null}
      {visual.kind === "pulse" ? (
        <span aria-hidden className="relative flex size-2.5">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary/60" />
          <span className="relative inline-flex size-2.5 rounded-full bg-primary" />
        </span>
      ) : null}
      {visual.kind === "speaking" ? (
        <span aria-hidden className="flex items-end gap-0.5">
          <span className="block h-3 w-1 animate-pulse rounded-sm bg-primary [animation-delay:0ms]" />
          <span className="block h-4 w-1 animate-pulse rounded-sm bg-primary [animation-delay:120ms]" />
          <span className="block h-2 w-1 animate-pulse rounded-sm bg-primary [animation-delay:240ms]" />
        </span>
      ) : null}
      <span className="font-medium">{visual.label}</span>
    </div>
  );
}
