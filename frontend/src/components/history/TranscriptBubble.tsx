import { cn } from "@/lib/utils";
import type { TranscriptTurn } from "@/lib/mockConversations";

type Props = { turn: TranscriptTurn };

/**
 * One transcript line in the History detail pane. Visually mirrors the live
 * chat surface so transcripts read as the same conversation pattern, but
 * labels the user side as "Caller" since the viewer is reviewing a past call
 * rather than participating in one.
 */
export function TranscriptBubble({ turn }: Props) {
  const isUser = turn.role === "user";
  return (
    <li
      className={cn(
        "flex flex-col gap-1",
        isUser ? "items-end" : "items-start",
      )}
    >
      <span className="text-xs font-medium text-muted-foreground">
        {isUser ? "Caller" : "Agent"}
      </span>
      <div
        className={cn(
          "max-w-[min(100%,20rem)] rounded-2xl px-4 py-2.5 text-sm",
          isUser
            ? "rounded-tr-sm bg-primary text-primary-foreground"
            : "rounded-tl-sm bg-muted text-foreground",
        )}
      >
        {turn.text}
      </div>
    </li>
  );
}
