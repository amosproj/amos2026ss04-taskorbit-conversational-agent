import { Link } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatRelativeStart } from "@/lib/formatTime";

export type RecentConversation = {
  id: string;
  agent_name: string;
  started_at: string;
};

const MAX_RECENT = 5;

/**
 * Home-screen "Recent" panel. Shows the most recent conversations as compact
 * rows (agent + relative time) that link into History, with a view-all footer.
 * When there are none yet, nudges the user toward a first call.
 */
export function RecentConversations({
  conversations,
  isLoading = false,
  error = false,
  className,
}: {
  conversations: RecentConversation[];
  isLoading?: boolean;
  error?: boolean;
  className?: string;
}) {
  // Sort by actual instant (timezone-agnostic) so mixed ISO offsets still order
  // correctly; newest first.
  const recent = [...conversations]
    .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime())
    .slice(0, MAX_RECENT);

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Recent</CardTitle>
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="text-sm text-muted-foreground">Couldn't load recent conversations.</p>
        ) : isLoading && recent.length === 0 ? (
          <div className="flex flex-col gap-2" aria-hidden>
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-8 animate-pulse rounded-md bg-muted/50" />
            ))}
          </div>
        ) : recent.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No conversations yet. Start your first call and it will show up here.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            <ul className="flex flex-col">
              {recent.map((c) => (
                <li key={c.id}>
                  <Link
                    to={`/history?c=${c.id}`}
                    className="-mx-2 flex items-center justify-between gap-3 rounded-md px-2 py-2 text-sm transition-colors hover:bg-muted/50"
                  >
                    <span className="truncate font-medium">{c.agent_name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {formatRelativeStart(c.started_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
            <Link
              to="/history"
              className="px-0.5 pt-1 text-sm text-primary underline underline-offset-2 transition-colors hover:text-primary/80"
            >
              View all {conversations.length} in History
            </Link>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
