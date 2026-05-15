/**
 * Active-call control surface — new dock design.
 *
 * Layout: [pill input (flex-1)] [Voice/Mic state btn] [End call btn]
 *
 * Pill input switches between:
 *   - text textarea + send arrow  (idle_in_call / speaking)
 *   - live waveform + timer + stop square  (recording)
 *
 * Voice button reflects call phase: idle → "Voice", recording →
 * "Listening", thinking → "Sending…", speaking → "Speaking".
 *
 * Must be rendered inside <LiveKitRoom>: uses useMicRecorder which
 * depends on the room context.
 */

import { useEffect, useId, useRef, useState } from "react";
import { ArrowUp, PhoneOff, Square, Wand2 } from "lucide-react";

import { Waveform } from "@/components/chat/Waveform";
import { cn } from "@/lib/utils";
import { useMicRecorder } from "@/hooks/useMicRecorder";
import { useSilenceDetection } from "@/hooks/useSilenceDetection";
import { useVoiceActivityMonitor } from "@/hooks/useVoiceActivityMonitor";
import type { CallStatus } from "@/types/callState";

type Props = {
  status: CallStatus;
  onPhase: (phase: CallStatus) => void;
  onEnd: () => void;
  onSendText: (text: string) => void;
  onTriggerConfirmation: () => void;
  onMicError: (message: string | null) => void;
};

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

const VOICE_BTN_STATES: Record<string, { label: string; cls: string }> = {
  idle_in_call: { label: "Voice", cls: "" },
  recording: { label: "Listening", cls: "listening" },
  thinking: { label: "Sending…", cls: "processing" },
  speaking: { label: "Speaking", cls: "speaking" },
  connecting: { label: "Voice", cls: "" },
  reconnecting: { label: "Voice", cls: "" },
  awaiting_confirmation: { label: "Voice", cls: "" },
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
  const [elapsed, setElapsed] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const inputId = useId();

  useEffect(() => {
    if (mic.error) onMicError(mic.error);
  }, [mic.error, onMicError]);

  // Recording timer
  useEffect(() => {
    if (status !== "recording") {
      setElapsed(0);
      return;
    }
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [status]);

  const handleStartRecording = async (): Promise<void> => {
    try {
      await mic.enable();
      onPhase("recording");
    } catch {
      // useMicRecorder surfaces the error via mic.error
    }
  };

  const handleInterruptAndSpeak = async (): Promise<void> => {
    await mic.sendInterrupt();
    try {
      await mic.enable();
      onPhase("recording");
    } catch {
      // useMicRecorder surfaces the error via mic.error
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

  // Automatically interrupt the agent when the user starts speaking during
  // TTS playback. Uses a separate getUserMedia stream (not published to LiveKit)
  // so the mic can monitor ambient audio without sending it over the network.
  useVoiceActivityMonitor({
    active: status === "speaking",
    onSpeech: () => {
      void handleInterruptAndSpeak();
    },
  });

  const handleSendText = (): void => {
    const text = draft.trim();
    if (!text) return;
    onSendText(text);
    setDraft("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const handleVoiceBtnClick = (): void => {
    if (status === "recording") {
      void handleSendUtterance();
    } else if (status === "speaking") {
      void handleInterruptAndSpeak();
    } else if (status === "idle_in_call") {
      void handleStartRecording();
    }
  };

  const recording = status === "recording";
  const thinking = status === "thinking";
  const voiceBtnDisabled =
    mic.starting || status === "connecting" || status === "thinking" || status === "reconnecting";

  const { label: voiceLabel, cls: voiceCls } = VOICE_BTN_STATES[status] ?? {
    label: "Voice",
    cls: "",
  };

  const textDisabled = status !== "idle_in_call" && status !== "speaking";

  return (
    <div className="rounded-xl border bg-card p-3.5">
      <div className="flex items-center gap-2.5">
        {/* ── Pill input ── */}
        <div
          className={cn(
            "flex flex-1 items-end gap-2 rounded-full border bg-background px-5 py-2 transition-colors",
            "focus-within:border-primary/40",
          )}
        >
          {recording ? (
            /* Recording mode: waveform + timer + stop */
            <>
              <Waveform levelsRef={mic.levelsRef} active className="h-9 flex-1" />
              <span className="min-w-[42px] text-right font-mono text-sm tabular-nums text-muted-foreground">
                {formatElapsed(elapsed)}
              </span>
              <button
                type="button"
                onClick={() => void handleStopRecording()}
                aria-label="Stop recording"
                className="flex size-8 shrink-0 items-center justify-center rounded-lg border text-foreground transition-colors hover:bg-muted"
              >
                <Square size={12} fill="currentColor" />
              </button>
            </>
          ) : (
            /* Text mode: auto-grow textarea + send */
            <>
              <label htmlFor={inputId} className="sr-only">
                Message
              </label>
              <textarea
                ref={textareaRef}
                id={inputId}
                rows={1}
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value);
                  e.target.style.height = "auto";
                  e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSendText();
                  }
                }}
                placeholder="Ask From Orbit."
                autoComplete="off"
                disabled={textDisabled}
                className={cn(
                  "flex-1 resize-none bg-transparent py-2 text-sm outline-none",
                  "max-h-[160px] overflow-y-auto leading-relaxed",
                  "placeholder:text-muted-foreground/60",
                  "disabled:cursor-not-allowed disabled:opacity-50",
                )}
              />
              <button
                type="button"
                onClick={handleSendText}
                disabled={textDisabled || !draft.trim()}
                aria-label="Send message"
                className={cn(
                  "flex size-9 shrink-0 items-center justify-center rounded-full transition-all",
                  "bg-primary text-primary-foreground hover:bg-primary/90 active:scale-95",
                  "disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground",
                )}
              >
                <ArrowUp size={16} />
              </button>
            </>
          )}
        </div>

        {/* ── Voice / Mic state button ── */}
        <button
          type="button"
          onClick={handleVoiceBtnClick}
          disabled={voiceBtnDisabled}
          aria-label={voiceLabel}
          className={cn(
            "inline-flex items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-medium",
            "transition-all duration-200",
            "disabled:cursor-not-allowed disabled:opacity-50",
            // idle
            voiceCls === "" && "border-border bg-card text-foreground hover:bg-muted",
            // listening (recording)
            voiceCls === "listening" &&
              "border-transparent bg-primary text-primary-foreground shadow-[0_0_0_4px_hsl(var(--primary)/0.18)]",
            // speaking
            voiceCls === "speaking" &&
              "border-transparent bg-violet-500 text-white shadow-[0_0_0_4px_rgb(139_92_246/0.22)]",
            // processing
            voiceCls === "processing" &&
              "border-transparent bg-amber-500 text-white shadow-[0_0_0_4px_rgb(245_158_11/0.22)]",
          )}
        >
          {/* Pulse icon (idle / processing) or inline waveform (listening / speaking) */}
          {voiceCls === "listening" || voiceCls === "speaking" ? (
            <VoiceWaveBars active />
          ) : (
            <VoicePulseIcon active={voiceCls === "processing"} />
          )}
          <span>{voiceLabel}</span>
        </button>

        {/* ── Demo confirmation (icon-only, unobtrusive) ── */}
        <button
          type="button"
          onClick={onTriggerConfirmation}
          aria-label="Demo: trigger agent confirmation"
          title="Demo: simulate the agent asking for confirmation"
          className="flex size-9 shrink-0 items-center justify-center rounded-full border bg-card text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <Wand2 size={15} />
        </button>

        {/* ── End call ── */}
        <button
          type="button"
          onClick={onEnd}
          aria-label="End call"
          className={cn(
            "flex size-11 shrink-0 items-center justify-center rounded-full",
            "bg-destructive/15 text-destructive border border-transparent",
            "transition-all hover:bg-destructive hover:text-destructive-foreground",
          )}
        >
          <PhoneOff size={16} />
        </button>
      </div>

      {/* Recording-state hint */}
      {thinking && (
        <p className="mt-2.5 text-center text-xs text-muted-foreground">
          Processing your message&hellip;
        </p>
      )}
    </div>
  );
}

/* ── Small decorative sub-components ── */

function VoicePulseIcon({ active }: { active: boolean }) {
  return (
    <span className="relative flex size-4 items-center justify-center">
      {active ? (
        <>
          <span className="absolute inset-0 animate-ping rounded-full border border-current opacity-70" />
          <span className="absolute inset-0 animate-ping rounded-full border border-current opacity-40 [animation-delay:0.6s]" />
        </>
      ) : (
        <>
          <span className="absolute inset-0 animate-ping rounded-full border border-current opacity-60" />
          <span className="absolute inset-0 animate-ping rounded-full border border-current opacity-35 [animation-delay:0.6s]" />
        </>
      )}
      <span className="relative size-1.5 rounded-full bg-current" />
    </span>
  );
}

function VoiceWaveBars({ active }: { active: boolean }) {
  return (
    <span className="flex items-center gap-[3px]" aria-hidden>
      {[0, 1, 2, 3, 4].map((i) => (
        <span
          key={i}
          className={cn(
            "w-[2px] rounded-sm bg-current",
            active ? "animate-[wavebar_1.1s_ease-in-out_infinite]" : "h-1",
          )}
          style={
            active
              ? {
                  animationDelay: `${i * 0.12}s`,
                  height: `${8 + Math.abs(2 - i) * 4}px`,
                }
              : undefined
          }
        />
      ))}
    </span>
  );
}
