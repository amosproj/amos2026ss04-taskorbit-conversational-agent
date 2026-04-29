import { useId, useState } from "react";
import { Mic, PhoneOff, Play, RefreshCw, Send, Wand2 } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { CallStatus } from "@/types/callState";

type Props = {
  status: CallStatus;
  onStart: () => void;
  onEnd: () => void;
  onSendText: (text: string) => void;
  onTriggerConfirmation: () => void;
  onRestart: () => void;
};

/**
 * Bottom control surface — shape changes by call phase.
 *
 * - `idle`: primary "Start session" CTA, with the text-fallback input
 *   tucked behind a disclosure so voice stays the headline.
 * - active states: large mic button (visually active during listening),
 *   destructive "End call", and the same text-fallback disclosure.
 *   A small dev-only button retriggers a confirmation for demo use.
 * - `ended`: "Start a new session" + a link into the History page so
 *   reviewers can see the call surfaced on the persistence side.
 *
 * The mic is intentionally non-functional in Sprint 2 — LiveKit + the
 * agent worker land in #14/#15/#26 and will hook into the same status
 * transitions.
 */
export function CallControls({
  status,
  onStart,
  onEnd,
  onSendText,
  onTriggerConfirmation,
  onRestart,
}: Props) {
  const [draft, setDraft] = useState("");
  const inputId = useId();

  const isActive =
    status === "connecting" ||
    status === "listening" ||
    status === "thinking" ||
    status === "speaking";

  function submitText() {
    const text = draft.trim();
    if (!text) return;
    onSendText(text);
    setDraft("");
  }

  if (status === "idle") {
    return (
      <Card>
        <CardContent className="flex flex-col gap-3 py-4">
          <Button size="lg" onClick={onStart} type="button" className="w-full">
            <Play data-icon="inline-start" />
            Start session
          </Button>
          <details className="group">
            <summary className="cursor-pointer text-center text-sm text-muted-foreground transition-colors hover:text-foreground">
              Use text instead
            </summary>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                submitText();
              }}
              className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center"
            >
              <label htmlFor={inputId} className="sr-only">
                Message
              </label>
              <Input
                id={inputId}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Type a message (debug / fallback)…"
                autoComplete="off"
                className="min-w-0 flex-1"
              />
              <Button type="submit" disabled={!draft.trim()}>
                <Send data-icon="inline-start" />
                Send
              </Button>
            </form>
          </details>
        </CardContent>
      </Card>
    );
  }

  if (status === "ended") {
    return (
      <Card>
        <CardContent className="flex flex-col items-stretch gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            Call ended — the transcript and any extracted data are now
            available in History.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link to="/history">View in history</Link>
            </Button>
            <Button size="sm" onClick={onRestart} type="button">
              <RefreshCw data-icon="inline-start" />
              Start a new session
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Active call states (connecting, listening, thinking, speaking) —
  // confirmation phase is rendered by ConfirmationPrompt outside this
  // component, so we don't need a branch for it here.
  return (
    <Card>
      <CardContent className="flex flex-col gap-3 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Button
              type="button"
              size="icon"
              variant={status === "listening" ? "default" : "outline"}
              className={cn(
                "size-12 rounded-full",
                status === "listening" &&
                  "ring-2 ring-primary/40 ring-offset-2 ring-offset-background",
              )}
              aria-label={
                status === "listening"
                  ? "Microphone active (mock)"
                  : "Microphone (mock — voice lands in Sprint 3)"
              }
              disabled={!isActive}
            >
              <Mic className="size-5" />
            </Button>
            <p className="text-sm text-muted-foreground">
              Voice pipeline lands in Sprint 3 (#14, #15, #26). For now,
              the mic is a visual placeholder.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={onTriggerConfirmation}
              type="button"
              title="Demo: simulate the agent asking for confirmation before a tool call."
            >
              <Wand2 data-icon="inline-start" />
              Demo confirmation
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={onEnd}
              type="button"
            >
              <PhoneOff data-icon="inline-start" />
              End call
            </Button>
          </div>
        </div>
        <details className="group">
          <summary className="cursor-pointer text-sm text-muted-foreground transition-colors hover:text-foreground">
            Use text instead
          </summary>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submitText();
            }}
            className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center"
          >
            <label htmlFor={inputId} className="sr-only">
              Message
            </label>
            <Input
              id={inputId}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Type a message (debug / fallback)…"
              autoComplete="off"
              className="min-w-0 flex-1"
              disabled={status !== "listening"}
            />
            <Button
              type="submit"
              disabled={status !== "listening" || !draft.trim()}
            >
              <Send data-icon="inline-start" />
              Send
            </Button>
          </form>
        </details>
      </CardContent>
    </Card>
  );
}
