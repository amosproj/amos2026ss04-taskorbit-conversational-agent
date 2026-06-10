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
  formatRelativeStart,
  formatDuration,
}: Props) {
  const toolCount = conversation.tool_count;
  return (
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
      <div className="flex flex-col gap-1.5 p-4">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate font-medium">{conversation.agent_name}</span>
          <span className="shrink-0 text-xs text-muted-foreground">
            {formatRelativeStart(conversation.started_at)}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          {conversation.duration_seconds !== null && (
            <Badge variant="secondary">{formatDuration(conversation.duration_seconds)}</Badge>
          )}
          {toolCount > 0 ? (
            <Badge variant="outline">
              {toolCount} {toolCount === 1 ? "tool" : "tools"}
            </Badge>
          ) : null}
        </div>
      </div>
    </button>
  );
}
