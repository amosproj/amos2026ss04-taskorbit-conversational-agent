import { useEffect, useRef, useState } from "react";
import { DatabaseZap, Loader2, MessageSquareDashed } from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

import {
  ConversationListItem,
  type ConversationRow,
} from "@/components/history/ConversationListItem";
import { SlotExtractionCard } from "@/components/history/SlotExtractionCard";
import { TranscriptBubble } from "@/components/history/TranscriptBubble";
import { Empty } from "@/components/Empty";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  deleteConversation,
  getConversationHistory,
  getConversations,
  type ConversationHistory,
} from "@/lib/conversationApi";

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
  const diffDays = Math.round((startOfDay(now).getTime() - startOfDay(then).getTime()) / dayMs);
  const time = then.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
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

function durationSeconds(startedAt: string, endedAt: string | null): number | null {
  if (!endedAt) return null;
  return Math.round((new Date(endedAt).getTime() - new Date(startedAt).getTime()) / 1000);
}

const lgBreakpointPx = 1024;

export function HistoryPage() {
  const [conversations, setConversations] = useState<ConversationRow[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedHistory, setSelectedHistory] = useState<ConversationHistory | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const detailRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getConversations()
      .then((data) => {
        setConversations(
          data.conversations.map((c) => ({
            id: c.id,
            agent_name: c.agent_name,
            started_at: c.started_at,
            duration_seconds: durationSeconds(c.started_at, c.ended_at),
            tool_count: 0,
          })),
        );
      })
      .catch(() => setListError("Failed to load conversations."))
      .finally(() => setListLoading(false));
  }, []);

  const handleSelect = (id: string) => {
    setSelectedId(id);
    setDetailLoading(true);
    setSelectedHistory(null);

    if (typeof window !== "undefined" && window.innerWidth < lgBreakpointPx) {
      detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    getConversationHistory(id)
      .then((h) => {
        setSelectedHistory(h);
        // Update tool_count in list once detail is loaded. Count distinct tools:
        // each different tool invoked (e.g. collect_user_info, end_call) adds one,
        // but the same tool firing on multiple turns is not counted again.
        const distinctTools = new Set(h.tool_executions.map((t) => t.tool_id)).size;
        setConversations((prev) =>
          prev.map((c) => (c.id === id ? { ...c, tool_count: distinctTools } : c)),
        );
      })
      .catch(() => setSelectedHistory(null))
      .finally(() => setDetailLoading(false));
  };

  const handleDeleteConfirmed = async () => {
    if (!pendingDeleteId) return;
    setDeleting(true);
    try {
      await deleteConversation(pendingDeleteId);
      setConversations((prev) => prev.filter((c) => c.id !== pendingDeleteId));
      if (selectedId === pendingDeleteId) {
        setSelectedId(null);
        setSelectedHistory(null);
      }
    } catch {
      // If the conversation was already gone, still remove it from local state
      setConversations((prev) => prev.filter((c) => c.id !== pendingDeleteId));
      if (selectedId === pendingDeleteId) {
        setSelectedId(null);
        setSelectedHistory(null);
      }
    } finally {
      setDeleting(false);
      setPendingDeleteId(null);
    }
  };

  const selectedMeta = conversations.find((c) => c.id === selectedId) ?? null;

  const transcriptTurns =
    selectedHistory?.messages.map((m) => ({
      id: String(m.id),
      role: m.role as "user" | "assistant",
      text: m.content,
      isFinal: true as const,
    })) ?? [];

  return (
    <section className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <header className="space-y-1">
        <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
          History
        </p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Conversation history</h1>
        <p className="text-sm text-muted-foreground">
          Past calls grouped by recency. Select one to inspect the transcript and any data the agent
          collected during the call.
        </p>
      </header>

      <div className="mt-8 grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)_18rem]">
        {/* Left: conversation list */}
        <aside aria-label="Past conversations">
          <ScrollArea className="h-[min(70vh,40rem)] pr-2">
            {listLoading ? (
              <div className="flex items-center justify-center py-12 text-muted-foreground">
                <Loader2 className="size-5 animate-spin" />
              </div>
            ) : listError ? (
              <p className="py-8 text-center text-sm text-destructive">{listError}</p>
            ) : conversations.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                No conversations yet.
              </p>
            ) : (
              <ul className="flex flex-col gap-3">
                {conversations.map((c) => (
                  <li key={c.id}>
                    <ConversationListItem
                      conversation={c}
                      selected={c.id === selectedId}
                      onSelect={() => handleSelect(c.id)}
                      onDelete={() => setPendingDeleteId(c.id)}
                      formatRelativeStart={formatRelativeStart}
                      formatDuration={formatDuration}
                    />
                  </li>
                ))}
              </ul>
            )}
          </ScrollArea>
        </aside>

        {/* Centre: transcript */}
        <div ref={detailRef} className="flex min-w-0 flex-col gap-6">
          {selectedId === null ? (
            <Empty
              icon={MessageSquareDashed}
              title="Pick a conversation"
              description="Select a past call from the list to view the transcript and any data extracted during the call."
            />
          ) : detailLoading ? (
            <div className="flex items-center justify-center py-20 text-muted-foreground">
              <Loader2 className="size-5 animate-spin" />
            </div>
          ) : selectedHistory !== null ? (
            <Card>
              <CardHeader className="border-b">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="space-y-1">
                    <CardTitle>{selectedMeta?.agent_name ?? selectedHistory.agent_name}</CardTitle>
                    <CardDescription>
                      {formatStartedAt(selectedHistory.started_at)}
                      {selectedMeta?.duration_seconds != null &&
                        ` · ${formatDuration(selectedMeta.duration_seconds)}`}
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="pt-6">
                <ScrollArea className="h-[min(50vh,28rem)] pr-3">
                  {transcriptTurns.length > 0 ? (
                    <ul className="flex flex-col gap-4" aria-label="Transcript">
                      {transcriptTurns.map((turn) => (
                        <TranscriptBubble key={turn.id} turn={turn} history />
                      ))}
                    </ul>
                  ) : (
                    <p className="py-8 text-center text-sm text-muted-foreground">
                      No messages recorded for this conversation.
                    </p>
                  )}
                </ScrollArea>
              </CardContent>
            </Card>
          ) : (
            <p className="py-8 text-center text-sm text-destructive">
              Failed to load conversation detail.
            </p>
          )}
        </div>

        {/* Right: extracted data with tool attribution */}
        <aside aria-label="Extracted data" className="min-w-0">
          {selectedId !== null && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Extracted data</CardTitle>
                <CardDescription>
                  Values the agent saved during the call, attributed to the tool that extracted
                  them.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {detailLoading ? (
                  <div className="flex justify-center py-6 text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" />
                  </div>
                ) : selectedHistory && selectedHistory.slot_extractions.length > 0 ? (
                  <SlotExtractionCard extractions={selectedHistory.slot_extractions} />
                ) : (
                  <Empty
                    icon={DatabaseZap}
                    title="No data extracted"
                    description="The agent didn't fire a data extraction tool during this call."
                  />
                )}
              </CardContent>
            </Card>
          )}
        </aside>
      </div>

      <AlertDialog
        open={pendingDeleteId !== null}
        onOpenChange={(open) => {
          if (!open && !deleting) setPendingDeleteId(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete conversation?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently remove the conversation and all its messages. This cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                handleDeleteConfirmed();
              }}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? <Loader2 className="size-4 animate-spin" /> : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
