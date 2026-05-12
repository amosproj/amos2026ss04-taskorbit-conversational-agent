/**
 * Pre/post-call control surface.
 *
 * - `idle`    — primary "Start session" CTA, with the text-fallback
 *               input tucked behind a disclosure so voice stays the
 *               headline.
 * - `ended`   — "Start a new session" + a link into the History page.
 *
 * The in-call surface (mic, Stop/Send, End call) lives in
 * `InCallControls` so it can read `useLocalParticipant` from inside a
 * `<LiveKitRoom>`. `CallControls` is still rendered in pre/post-call
 * states because those don't need a room context.
 */

import { useId, useState } from "react";
import { Play, RefreshCw, Send } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import type { CallStatus } from "@/types/callState";

type Props = {
  status: CallStatus;
  onStart: () => void;
  onSendText: (text: string) => void;
  onRestart: () => void;
};

export function CallControls({ status, onStart, onSendText, onRestart }: Props) {
  const [draft, setDraft] = useState("");
  const inputId = useId();

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
            Call ended — the transcript and any extracted data are now available in History.
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

  return null;
}
