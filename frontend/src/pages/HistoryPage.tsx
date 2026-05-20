import { useEffect, useRef, useState } from "react";
import { MessageSquareDashed } from "lucide-react";

import { Empty } from "@/components/Empty";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { getConversations, getConversationMessages } from "@/lib/conversationApi";

const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

function formatStartedAt(iso: string): string {
  return dateTimeFormatter.format(new Date(iso));
}

type Conversation = {
  id: string;
  agent_name: string;
  started_at: string;
  ended_at: string | null;
};

type Message = {
  id: number;
  role: string;
  content: string;
  created_at: string;
};

const lgBreakpointPx = 1024;

export function HistoryPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const detailRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const data = await getConversations();
        setConversations(data.conversations || []);
      } catch (err) {
        console.error("Failed to load conversations:", err);
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    const load = async () => {
      try {
        const data = await getConversationMessages(selectedId);
        setMessages(data.messages || []);
      } catch (err) {
        console.error("Failed to load messages:", err);
      }
    };
    void load();
  }, [selectedId]);

  useEffect(() => {
    if (selectedId === null) return;
    if (typeof window === "undefined") return;
    if (window.innerWidth >= lgBreakpointPx) return;
    detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [selectedId]);

  const selected = conversations.find((c) => c.id === selectedId) ?? null;

  return (
    <section className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <header className="space-y-1">
        <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
          History
        </p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Conversation history</h1>
        <p className="text-sm text-muted-foreground">
          Past conversations grouped by recency. Select one to inspect the transcript.
        </p>
      </header>

      <div className="mt-8 grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <aside aria-label="Past conversations">
          <ScrollArea className="h-[min(70vh,40rem)] pr-2">
            {loading ? (
              <p className="text-sm text-muted-foreground">Loading...</p>
            ) : conversations.length === 0 ? (
              <p className="text-sm text-muted-foreground">No conversations yet.</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {conversations.map((c) => (
                  <li key={c.id}>
                    <button
                      onClick={() => setSelectedId(c.id)}
                      className={`w-full rounded-lg border p-4 text-left transition-colors hover:bg-muted ${
                        c.id === selectedId ? "border-primary bg-muted" : "border-border"
                      }`}
                    >
                      <p className="font-medium">{c.agent_name}</p>
                      <p className="text-sm text-muted-foreground">
                        {formatStartedAt(c.started_at)}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </ScrollArea>
        </aside>

        <div ref={detailRef} className="flex min-w-0 flex-col gap-6">
          {selected !== null ? (
            <Card>
              <CardHeader className="border-b">
                <CardTitle>{selected.agent_name}</CardTitle>
                <CardDescription>{formatStartedAt(selected.started_at)}</CardDescription>
              </CardHeader>
              <CardContent className="pt-6">
                <ScrollArea className="h-[min(50vh,28rem)] pr-3">
                  {messages.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      No messages in this conversation.
                    </p>
                  ) : (
                    <ul className="flex flex-col gap-4" aria-label="Transcript">
                      {messages.map((msg) => (
                        <li
                          key={msg.id}
                          className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                        >
                          <div
                            className={`max-w-[80%] rounded-lg px-4 py-2 text-sm ${
                              msg.role === "user"
                                ? "bg-primary text-primary-foreground"
                                : "bg-muted text-foreground"
                            }`}
                          >
                            {msg.content}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </ScrollArea>
              </CardContent>
            </Card>
          ) : (
            <Empty
              icon={MessageSquareDashed}
              title="Pick a conversation"
              description="Select a past conversation from the list to view the transcript."
            />
          )}
        </div>
      </div>
    </section>
  );
}
