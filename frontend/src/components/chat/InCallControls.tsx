/**
 * Active-call control surface — mic toggle, Stop/Send, End call, plus
 * the same text fallback the idle screen offers.
 *
 * This component must be rendered inside a `<LiveKitRoom>`: it reads
 * `useMicRecorder` which depends on the room context. It has no
 * lifecycle responsibilities of its own — all events bubble up to the
 * parent via the supplied callbacks.
 */

import { useEffect, useId, useState } from "react";
import { PhoneOff, Send, Wand2 } from "lucide-react";

import { MicButton } from "@/components/chat/MicButton";
import { RecordingControls } from "@/components/chat/RecordingControls";
import { Waveform } from "@/components/chat/Waveform";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useMicRecorder } from "@/hooks/useMicRecorder";
import { useSilenceDetection } from "@/hooks/useSilenceDetection";
import type { CallStatus } from "@/types/callState";

type Props = {
  status: CallStatus;
  /** Called after the user starts/stops/sends their utterance. */
  onPhase: (phase: CallStatus) => void;
  /** End the whole call. */
  onEnd: () => void;
  /** Text-fallback path (kept for debugging / deaf users). */
  onSendText: (text: string) => void;
  /** Demo-only confirmation trigger. */
  onTriggerConfirmation: () => void;
  /** Surfacing of mic permission errors to the parent. */
  onMicError: (message: string | null) => void;
};

export function InCallControls({
  status,
  onPhase,
  onEnd,
  onSendText,
  onTriggerConfirmation,
  onMicError,
}: Props) {
  const mic = useMicRecorder();
  const [draft, setDraft] = useState("");

  const inputId = useId();

  // Mic errors live on the recorder hook; lift them to the parent so
  // the global toast can render them without coupling InCallControls
  // to the parent's state.
  useEffect(() => {
    if (mic.error) onMicError(mic.error);
  }, [mic.error, onMicError]);

  const handleStartRecording = async (): Promise<void> => {
    try {
      await mic.enable();
      onPhase("recording");
    } catch {
      // useMicRecorder already surfaces the error via mic.error.
    }
  };

  const handleInterruptAndSpeak = async (): Promise<void> => {
    await mic.sendInterrupt();
    try {
      await mic.enable();
      onPhase("recording");
    } catch {
      // useMicRecorder already surfaces the error via mic.error.
    }
  };

  const handleStopRecording = async (): Promise<void> => {
    await mic.disable();
    onPhase("idle_in_call");
  };

  const handleSendUtterance = async (): Promise<void> => {
    await mic.sendUtterance();
    onPhase("thinking");
  };

  useSilenceDetection({
    levelsRef: mic.levelsRef,
    active: status === "recording",
    onSilence: () => {
      void handleSendUtterance();
    },
  });

  const handleSendText = (): void => {
    const text = draft.trim();
    if (!text) return;
    onSendText(text);
    setDraft("");
  };

  const recording = status === "recording";
  const textInputDisabled = status !== "idle_in_call" && status !== "speaking";

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <MicButton
              status={status}
              starting={mic.starting}
              onStart={
                status === "speaking"
                  ? () => void handleInterruptAndSpeak()
                  : () => void handleStartRecording()
              }
              onStop={() => void handleStopRecording()}
            />
            {recording ? (
              <RecordingControls
                onStop={() => void handleStopRecording()}
                onSend={() => void handleSendUtterance()}
              />
            ) : null}
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
            <Button variant="destructive" size="sm" onClick={onEnd} type="button">
              <PhoneOff data-icon="inline-start" />
              End call
            </Button>
          </div>
        </div>

        <Waveform levelsRef={mic.levelsRef} active={recording} className="h-8 w-full" />

        <details className="group">
          <summary className="cursor-pointer text-sm text-muted-foreground transition-colors hover:text-foreground">
            Use text instead
          </summary>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSendText();
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
              disabled={textInputDisabled}
            />
            <Button type="submit" disabled={textInputDisabled || !draft.trim()}>
              <Send data-icon="inline-start" />
              Send
            </Button>
          </form>
        </details>
      </CardContent>
    </Card>
  );
}
