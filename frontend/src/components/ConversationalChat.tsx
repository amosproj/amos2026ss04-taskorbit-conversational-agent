import { useEffect, useId, useRef, useState } from "react";
import { Mic } from "lucide-react";

import { useBackendHealth } from "@/hooks/useBackendHealth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";

type ChatMessage = { id: string; role: "user" | "assistant"; text: string };

const INITIAL_MESSAGES: ChatMessage[] = [
  {
    id: "welcome",
    role: "assistant",
    text: "Hi — I am a mock agent for now. Type a message to try the UI; responses are faked for issue #5.",
  },
];

function mockAssistantReply(userText: string) {
  return `You said: “${userText}”. (Mock reply — the real LLM + LiveKit path comes in later stories.)`;
}

export function ConversationalChat() {
  const appName = import.meta.env.VITE_APP_NAME ?? "TaskOrbit";
  const livekitUrl = import.meta.env.VITE_LIVEKIT_URL ?? "";
  const { health, apiUrl } = useBackendHealth();
  const formId = useId();
  const inputId = `${formId}-text`;

  const [messages, setMessages] = useState<ChatMessage[]>(INITIAL_MESSAGES);
  const [draft, setDraft] = useState("");

  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;

    setDraft("");
    const userId = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `u-${Date.now()}`;

    setMessages((m) => [...m, { id: userId, role: "user", text }]);

    window.setTimeout(() => {
      const aid =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : `a-${Date.now()}`;
      setMessages((m) => [...m, { id: aid, role: "assistant", text: mockAssistantReply(text) }]);
    }, 400);
  }

  return (
    <main className="min-h-svh bg-background text-foreground">
      <div className="mx-auto flex min-h-svh max-w-2xl flex-col gap-6 px-4 py-8 sm:px-6 sm:py-10">
        <header className="space-y-1">
          <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
            Conversational agent
          </p>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{appName}</h1>
          <p className="text-sm text-muted-foreground">
            Prototype UI (issue #5) — text chat is live; voice is a placeholder; backend status below.
          </p>
        </header>

        <Card>
          <CardHeader className="border-b">
            <CardTitle>Chat</CardTitle>
            <CardDescription>History and messages scroll here. System replies are mocked.</CardDescription>
          </CardHeader>
          <CardContent className="pt-6">
            <ScrollArea className="h-[min(50vh,28rem)] pr-3">
              <ul className="flex flex-col gap-4" aria-label="Chat messages">
                {messages.map((msg) => (
                  <li
                    key={msg.id}
                    className={msg.role === "user" ? "flex flex-col items-end gap-1" : "flex flex-col items-start gap-1"}
                  >
                    <span className="text-xs font-medium text-muted-foreground">
                      {msg.role === "user" ? "You" : "Agent"}
                    </span>
                    <div
                      className={
                        msg.role === "user"
                          ? "max-w-[min(100%,20rem)] rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground"
                          : "max-w-[min(100%,20rem)] rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5 text-sm text-foreground"
                      }
                    >
                      {msg.text}
                    </div>
                  </li>
                ))}
                <div ref={endRef} className="h-px" aria-hidden />
              </ul>
            </ScrollArea>
          </CardContent>
          <CardFooter className="flex flex-col gap-3 border-t sm:flex-row sm:items-end">
            <form id={formId} onSubmit={onSubmit} className="flex w-full flex-col gap-2 sm:flex-row sm:items-center">
              <div className="flex shrink-0 justify-center sm:justify-start">
                <Button
                  type="button"
                  size="icon"
                  variant="outline"
                  disabled
                  className="size-10"
                  title="Voice — LiveKit + agent worker will connect here in a follow-up (placeholder for #5)."
                  aria-label="Voice (not available in this build)"
                >
                  <Mic className="size-4" />
                </Button>
              </div>
              <div className="flex w-full min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center">
                <label htmlFor={inputId} className="sr-only">
                  Message
                </label>
                <Input
                  id={inputId}
                  name="message"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="Type a message (debug / fallback)…"
                  autoComplete="off"
                  className="min-w-0 flex-1"
                />
                <Button type="submit" className="shrink-0 sm:min-w-[5rem]">
                  Send
                </Button>
              </div>
            </form>
          </CardFooter>
        </Card>

        <Card>
          <CardHeader className="space-y-1">
            <CardTitle className="text-base">Development wiring</CardTitle>
            <CardDescription>Verifies the same setup as the #17 health check. Optional when only UI work is needed.</CardDescription>
          </CardHeader>
          <CardContent className="text-sm">
            <dl className="space-y-2">
              <div className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
                <dt className="text-muted-foreground">Backend /health</dt>
                <dd className="font-mono text-right">
                  {health.status === "loading" && "checking…"}
                  {health.status === "ok" && (
                    <span className="text-green-600 dark:text-green-400">
                      ok · {health.service} v{health.version}
                    </span>
                  )}
                  {health.status === "error" && (
                    <span className="text-destructive">unreachable · {health.message}</span>
                  )}
                </dd>
              </div>
              <div className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
                <dt className="text-muted-foreground">VITE_API_URL</dt>
                <dd className="font-mono break-all text-right">{apiUrl || "(using Vite /api proxy)"}</dd>
              </div>
              <div className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
                <dt className="text-muted-foreground">VITE_LIVEKIT_URL</dt>
                <dd className="font-mono break-all text-right">{livekitUrl || "(unset)"}</dd>
              </div>
            </dl>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
