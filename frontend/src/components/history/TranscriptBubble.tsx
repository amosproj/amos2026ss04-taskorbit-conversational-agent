import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import type { TranscriptTurn } from "@/lib/mockConversations";

/** ~155 WPM — matches typical ElevenLabs TTS speaking pace. */
const MS_PER_WORD = 390;

type Props = {
  turn: TranscriptTurn & { isFinal?: boolean };
};

/**
 * One transcript bubble.
 *
 * Assistant turns animate word-by-word at speech rate. The last revealed
 * word is highlighted (currently being spoken). Once all words are shown,
 * plain text with no highlight.
 *
 * User turns and History views: plain text, no animation.
 */
export function TranscriptBubble({ turn }: Props) {
  const isUser = turn.role === "user";
  const [shownCount, setShownCount] = useState(0);

  // countRef mirrors shownCount so the timer closure always reads the
  // latest position without capturing a stale state value.
  const countRef = useRef(0);

  // Always holds the latest split words so the timer's stop condition
  // uses the most up-to-date length (important when text grows via streaming).
  const wordsRef = useRef<string[]>([]);
  const allWords = turn.text.trim().split(/\s+/).filter(Boolean);
  wordsRef.current = allWords;

  useEffect(() => {
    if (isUser || !turn.text) return;
    if (countRef.current >= wordsRef.current.length) return;

    // Resume from wherever we left off — handles growing text (streaming)
    // and also React StrictMode's mount→unmount→remount cycle correctly
    // because the cleanup always nulls timerRef before the next run.
    let count = countRef.current;

    const id = setInterval(() => {
      count++;
      countRef.current = count;
      setShownCount(count);
      if (count >= wordsRef.current.length) {
        clearInterval(id);
      }
    }, MS_PER_WORD);

    return () => {
      // Always clear AND null so StrictMode remount doesn't see a stale id
      // and the next effect run can start a fresh timer if needed.
      clearInterval(id);
    };
  }, [turn.text, isUser]);

  const shownWords = isUser ? allWords : allWords.slice(0, shownCount);

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
        {isUser ? turn.text : shownWords.join(" ")}
      </div>
    </li>
  );
}
