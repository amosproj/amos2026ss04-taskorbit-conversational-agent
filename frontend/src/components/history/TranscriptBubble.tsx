import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import type { TranscriptTurn } from "@/lib/mockConversations";

/** ~155 WPM — used only for static turns (greeting) that play via playSynthesizedSpeech. */
const MS_PER_WORD = 390;

type Props = {
  turn: TranscriptTurn & { isFinal?: boolean };
  /**
   * Pass true for assistant turns that are not streamed (e.g. the greeting).
   * These play audio via playSynthesizedSpeech so a fixed-rate timer is the
   * only way to approximate audio sync. Live streaming turns must NOT use
   * this — the stream's own delivery timing is already audio-synchronized.
   */
  animate?: boolean;
};

export function TranscriptBubble({ turn, animate = false }: Props) {
  const isUser = turn.role === "user";
  const shouldAnimate = animate && !isUser;

  const [shownCount, setShownCount] = useState(0);
  const countRef = useRef(0);
  const wordsRef = useRef<string[]>([]);
  const allWords = turn.text.trim().split(/\s+/).filter(Boolean);
  wordsRef.current = allWords;

  useEffect(() => {
    if (!shouldAnimate || !turn.text) return;
    if (countRef.current >= wordsRef.current.length) return;

    let count = countRef.current;
    const id = setInterval(() => {
      count++;
      countRef.current = count;
      setShownCount(count);
      if (count >= wordsRef.current.length) clearInterval(id);
    }, MS_PER_WORD);

    return () => clearInterval(id);
  }, [turn.text, shouldAnimate]);

  const displayText = shouldAnimate ? allWords.slice(0, shownCount).join(" ") : turn.text;

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
