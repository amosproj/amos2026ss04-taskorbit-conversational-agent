import { Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export type ConversationRow = {
  id: string;
  agent_name: string;
  started_at: string;
  duration_seconds: number | null;
  tool_count: number;
};

type Props = {
  conversation: ConversationRow;
  selected: boolean;
  onSelect: () => void;
  onDelete: () => void;
  formatRelativeStart: (iso: string) => string;
  formatDuration: (seconds: number) => string;
};

/**
 * Left-pane row for a past conversation. Native button so Enter/Space and
 * focus rings work without extra ARIA wiring; selection state surfaced via
 * `aria-current` and a subtle ring so screen-reader and visual users get the
 * same signal.
 */
export function ConversationListItem({
  conversation,
  selected,
  onSelect,
  onDelete,
  formatRelativeStart,
  formatDuration,
}: Props) {
  const toolCount = conversation.tool_count;
  // The row and the delete control are SIBLINGS inside a positioned wrapper —
  // never nest a button inside a button (invalid HTML + broken keyboard focus).
  // The wrapper owns `group` so the delete's hover-reveal still works.
  return (
    <div className="group relative">
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        className={cn(
          "relative block w-full rounded-lg border bg-card text-left text-card-foreground transition-colors",
          "hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          selected &&
            "bg-muted/40 ring-2 ring-primary/60 before:absolute before:inset-y-2 before:left-0 before:w-1 before:rounded-r before:bg-primary",
        )}
      >
        {/* pr-10 keeps text clear of the absolutely-positioned delete button. */}
        <div className="flex flex-col gap-1 p-4 pr-10">
          {/* Agent name: full width, wraps fully so long names are never cut off (#181). */}
          <span className="text-sm font-medium leading-snug break-words">
            {conversation.agent_name}
          </span>

          <div className="pt-0.5">
            <span className="text-xs text-muted-foreground">
              {formatRelativeStart(conversation.started_at)}
            </span>
          </div>

          {(conversation.duration_seconds !== null || toolCount > 0) && (
            <div className="flex flex-wrap items-center gap-1.5 pt-1">
              {conversation.duration_seconds !== null && (
                <Badge variant="secondary">{formatDuration(conversation.duration_seconds)}</Badge>
              )}
              {toolCount > 0 && (
                <Badge variant="outline">
                  {toolCount} {toolCount === 1 ? "tool" : "tools"}
                </Badge>
              )}
            </div>
          )}
        </div>
      </button>

      <button
        type="button"
        onClick={onDelete}
        aria-label="Delete conversation"
        className={cn(
          "absolute right-3 top-3 flex size-5 items-center justify-center rounded",
          "text-muted-foreground opacity-0 transition-opacity",
          "hover:bg-destructive/10 hover:text-destructive",
          "focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          "group-hover:opacity-100",
        )}
      >
        <Trash2 className="size-3" />
      </button>
    </div>
  );
}
