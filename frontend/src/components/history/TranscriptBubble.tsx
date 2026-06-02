import { ArrowRightLeft } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import type { TranscriptTurn } from "@/lib/mockConversations";

/** ~155 WPM — only used when the full text arrives at once with no prior streaming. */
const MS_PER_WORD = 390;

type Props = {
  turn: TranscriptTurn & { isFinal?: boolean };
  /** When true, skip all animation and show the full text immediately. */
  history?: boolean;
};

function SystemMarker({ text }: { text: string }) {
  const label = text.slice(1, -1); // strip surrounding [ ]
  const isTransfer = label.toLowerCase().startsWith("transferred");
  return (
    <li className="flex items-center gap-3 py-2">
      <span className="h-px flex-1 bg-border" />
      <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/60 px-3 py-1 text-xs font-medium text-muted-foreground">
        {isTransfer && <ArrowRightLeft aria-hidden className="size-3 shrink-0" />}
        {label}
      </span>
      <span className="h-px flex-1 bg-border" />
    </li>
  );
}

export function TranscriptBubble({ turn, history = false }: Props) {
  const isUser = turn.role === "user";

  if (!isUser && turn.text.startsWith("[") && turn.text.endsWith("]")) {
    return <SystemMarker text={turn.text} />;
  }

  // Once we see isFinal=false the turn is being streamed (LiveKit stream or
  // playWithWordSync timestamps). Text is already arriving at the right time
  // so we show it directly — the timer would only add unwanted delay.
  const wasStreamedRef = useRef(false);
  if (turn.isFinal === false) wasStreamedRef.current = true;
  const isStreaming = wasStreamedRef.current;

  const [shownCount, setShownCount] = useState(0);
  const countRef = useRef(0);
  const allWords = turn.text.trim().split(/\s+/).filter(Boolean);
  const wordsRef = useRef<string[]>([]);
  wordsRef.current = allWords;

  // Timer fallback: only for non-user, non-history, non-streaming turns where
  // the full sentence arrives in one shot (e.g. TTS fetch failed → full text).
  useEffect(() => {
    if (history || isUser || isStreaming || turn.isFinal === undefined || !turn.text) return;
    if (countRef.current >= wordsRef.current.length) return;

    let count = countRef.current;
    const id = setInterval(() => {
      count++;
      countRef.current = count;
      setShownCount(count);
      if (count >= wordsRef.current.length) clearInterval(id);
    }, MS_PER_WORD);

    return () => clearInterval(id);
  }, [turn.text, isUser, isStreaming, turn.isFinal, history]);

  const displayText = (() => {
    if (isUser || history) return turn.text;
    // History turns (isFinal undefined) and streaming turns: show as-is.
    if (turn.isFinal === undefined || isStreaming) return turn.text;
    // Full-text-at-once fallback: timer-paced reveal.
    return allWords.slice(0, shownCount).join(" ");
  })();

  return (
    <li className={cn("flex flex-col gap-1", isUser ? "items-end" : "items-start")}>
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
        {displayText}
      </div>
    </li>
  );
}
