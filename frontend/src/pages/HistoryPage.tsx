import { Fragment, useEffect, useRef, useState } from "react";
import { DatabaseZap, MessageSquareDashed } from "lucide-react";

import { ConversationListItem } from "@/components/history/ConversationListItem";
import { TranscriptBubble } from "@/components/history/TranscriptBubble";
import { TranscriptToolMarker } from "@/components/history/TranscriptToolMarker";
import { Empty } from "@/components/Empty";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  MOCK_CONVERSATIONS,
  type Conversation,
  type ToolFiring,
} from "@/lib/mockConversations";

const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

const dayMs = 1000 * 60 * 60 * 24;

function startOfDay(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

function formatStartedAt(iso: string): string {
  return dateTimeFormatter.format(new Date(iso));
}

function formatRelativeStart(iso: string): string {
  const now = new Date();
  const then = new Date(iso);
  const diffDays = Math.round(
    (startOfDay(now).getTime() - startOfDay(then).getTime()) / dayMs,
  );
  const time = then.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (diffDays === 0) return `Today, ${time}`;
  if (diffDays === 1) return `Yesterday, ${time}`;
  if (diffDays > 1 && diffDays < 7) return `${diffDays}d ago, ${time}`;
  return then.toLocaleDateString([], { month: "short", day: "numeric" });
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

const languageDisplayNames =
  typeof Intl !== "undefined" && "DisplayNames" in Intl
    ? new Intl.DisplayNames(undefined, { type: "language" })
    : null;

function formatLanguage(tag: string): string {
  return languageDisplayNames?.of(tag) ?? tag.toUpperCase();
}

function groupFiringsByTurn(firings: ToolFiring[]): Map<string, ToolFiring[]> {
  const map = new Map<string, ToolFiring[]>();
  for (const firing of firings) {
    const list = map.get(firing.triggered_after_turn_id) ?? [];
    list.push(firing);
    map.set(firing.triggered_after_turn_id, list);
  }
  return map;
}

// `lg` in Tailwind v4 is the 1024px breakpoint — anything below collapses
// the two-pane grid into a single column. On mobile/tablet the detail pane
// renders below the list, so we scroll it into view when a call is picked.
const lgBreakpointPx = 1024;

export function HistoryPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);

  const selected: Conversation | null =
    selectedId !== null
      ? (MOCK_CONVERSATIONS.find((c) => c.id === selectedId) ?? null)
      : null;

  const extractionRows: Array<[string, string | number | boolean]> = selected
    ? selected.tool_firings.flatMap((f) =>
        f.type === "data_extraction" ? Object.entries(f.values) : [],
      )
    : [];

  const firingsByTurn = selected
    ? groupFiringsByTurn(selected.tool_firings)
    : new Map<string, ToolFiring[]>();

  useEffect(() => {
    if (selectedId === null) return;
    if (typeof window === "undefined") return;
    if (window.innerWidth >= lgBreakpointPx) return;
    detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [selectedId]);

  return (
    <section className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <header className="space-y-1">
        <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
          History
        </p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Conversation history
        </h1>
        <p className="text-sm text-muted-foreground">
          Past calls grouped by recency. Select one to inspect the transcript
          and any data the agent collected during the call.
        </p>
      </header>

      <div className="mt-8 grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)_18rem]">
        <aside aria-label="Past conversations">
          <ScrollArea className="h-[min(70vh,40rem)] pr-2">
            <ul className="flex flex-col gap-3">
              {MOCK_CONVERSATIONS.map((c) => (
                <li key={c.id}>
                  <ConversationListItem
                    conversation={c}
                    selected={c.id === selectedId}
                    onSelect={() => setSelectedId(c.id)}
                    formatRelativeStart={formatRelativeStart}
                    formatDuration={formatDuration}
                  />
                </li>
              ))}
            </ul>
          </ScrollArea>
        </aside>

        <div ref={detailRef} className="flex min-w-0 flex-col gap-6">
          {selected !== null ? (
            <Card>
              <CardHeader className="border-b">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="space-y-1">
                    <CardTitle>
                      {selected.agent_name} · {selected.caller_label}
                    </CardTitle>
                    <CardDescription>
                      {formatStartedAt(selected.started_at)} ·{" "}
                      {formatDuration(selected.duration_seconds)}
                    </CardDescription>
                  </div>
                  <Badge variant="outline">
                    {formatLanguage(selected.language)}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="pt-6">
                <ScrollArea className="h-[min(50vh,28rem)] pr-3">
                  <ul
                    className="flex flex-col gap-4"
                    aria-label="Transcript"
                  >
                    {selected.transcript.map((turn) => {
                      const firings = firingsByTurn.get(turn.id) ?? [];
                      return (
                        <Fragment key={turn.id}>
                          <TranscriptBubble turn={turn} />
                          {firings.map((firing, i) => (
                            <TranscriptToolMarker
                              key={`${turn.id}-firing-${i}`}
                              firing={firing}
                            />
                          ))}
                        </Fragment>
                      );
                    })}
                  </ul>
                </ScrollArea>
              </CardContent>
            </Card>
          ) : (
            <Empty
              icon={MessageSquareDashed}
              title="Pick a conversation"
              description="Select a past call from the list to view the transcript and any data extracted during the call."
            />
          )}
        </div>

        <aside aria-label="Extracted data" className="min-w-0">
          {selected !== null ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Extracted data</CardTitle>
                <CardDescription>
                  Values the agent saved during the call via data extraction
                  tools.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {extractionRows.length > 0 ? (
                  <dl className="flex flex-col gap-3">
                    {extractionRows.map(([key, value]) => (
                      <div key={key} className="flex flex-col gap-0.5">
                        <dt className="text-xs text-muted-foreground">
                          {key}
                        </dt>
                        <dd className="font-mono text-sm break-all">
                          {String(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <Empty
                    icon={DatabaseZap}
                    title="No data extracted"
                    description="The agent didn't fire a data extraction tool during this call."
                  />
                )}
              </CardContent>
            </Card>
          ) : null}
        </aside>
      </div>
    </section>
  );
}
