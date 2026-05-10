/**
 * The big circular mic button at the centre of the call surface.
 *
 * Visual states:
 * - `idle_in_call` — outline button with a mic icon, "Tap to speak".
 * - `recording`    — primary fill, pulsing ring, accessible label
 *                    "Stop recording" (clicking the button doubles as
 *                    Stop, but the explicit Stop / Send buttons in
 *                    `RecordingControls` are the intended UX).
 * - `speaking`     — outline with mic, but click triggers an interrupt
 *                    of the agent's reply (re-enables the mic).
 *
 * The component is purely presentational. All side effects (mic enable
 * / disable, interrupt) come from props.
 */

import { Mic, MicOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { CallStatus } from "@/types/callState";

type Props = {
  status: CallStatus;
  starting: boolean;
  onStart: () => void;
  onStop: () => void;
};

export function MicButton({ status, starting, onStart, onStop }: Props) {
  const recording = status === "recording";
  const interrupting = status === "speaking";
  const disabled =
    starting ||
    status === "connecting" ||
    status === "thinking" ||
    status === "reconnecting";

  // The button toggles: tap-to-record from idle, tap-to-stop while
  // recording, tap-to-interrupt while the agent is speaking.
  const handleClick = (): void => {
    if (recording) {
      onStop();
      return;
    }
    onStart();
  };

  return (
    <Button
      type="button"
      size="icon"
      variant={recording ? "default" : "outline"}
      onClick={handleClick}
      disabled={disabled}
      aria-pressed={recording}
      aria-label={
        recording
          ? "Stop recording"
          : interrupting
            ? "Interrupt and speak"
            : "Start recording"
      }
      className={cn(
        "relative size-16 rounded-full transition-transform",
        recording &&
          "ring-4 ring-primary/40 ring-offset-2 ring-offset-background",
        recording && "scale-105",
      )}
    >
      {recording ? (
        // Pulsing red dot communicates active capture at a glance.
        <span aria-hidden className="relative flex size-3">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-destructive/70" />
          <span className="relative inline-flex size-3 rounded-full bg-destructive" />
        </span>
      ) : status === "idle_in_call" || status === "speaking" ? (
        <Mic className="size-6" />
      ) : (
        <MicOff className="size-6" />
      )}
    </Button>
  );
}
