/**
 * Active-call control surface — dock design.
 *
 * Layout: [pill input (flex-1)] [Voice toggle btn] [End call btn]
 *
 * Voice button is a continuous-mode toggle:
 *   OFF → click → ON  : starts recording immediately; after agent speaks,
 *                        auto-returns to recording without any user action.
 *   ON  → click → OFF : stops recording / cancels mode at any phase.
 *
 * Barge-in (useVoiceActivityMonitor) works transparently inside the cycle —
 * speaking into the mic while the agent is playing audio interrupts it and
 * shifts straight back into recording, then the cycle continues.
 *
 * Must be rendered inside <LiveKitRoom>: uses useMicRecorder which
 * depends on the room context.
 */

import { useEffect, useId, useRef, useState } from "react";
import { ArrowUp, PhoneOff, Wand2 } from "lucide-react";

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
  const [continuousMode, setContinuousMode] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const inputId = useId();

  useEffect(() => {
    if (mic.error) {
      onMicError(mic.error);
      // A mic error means we can't listen — exit continuous mode so the
      // button returns to idle rather than looping failed enable() calls.
      setContinuousMode(false);
    }
  }, [mic.error, onMicError]);

  // ── Core handlers ───────────────────────────────────────────────────────

  const handleStartRecording = async (): Promise<void> => {
    try {
      await mic.enable();
      onPhase("recording");
    } catch {
      // mic.error is set by useMicRecorder; the effect above exits the mode.
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

  const handleInterruptAndSpeak = async (): Promise<void> => {
    await mic.sendInterrupt();
    try {
      await mic.enable();
      onPhase("recording");
    } catch {
      // mic.error surfaced by useMicRecorder.
    }
  };

  // ── Stable ref so the auto-restart effect never captures a stale closure ─

  const handleStartRecordingRef = useRef(handleStartRecording);
  handleStartRecordingRef.current = handleStartRecording;

  // ── Continuous-mode auto-restart ─────────────────────────────────────────
  // After each agent turn (speaking → idle_in_call), automatically re-enable
  // the mic so the user can speak without pressing anything.
  useEffect(() => {
    if (!continuousMode) return;
    if (status !== "idle_in_call") return;
    void handleStartRecordingRef.current();
  }, [status, continuousMode]);

  // ── Silence / barge-in detection ─────────────────────────────────────────

  useSilenceDetection({
    levelsRef: mic.levelsRef,
    active: status === "recording",
    onSilence: () => {
      void handleSendUtterance();
    },
  });

  // Passively monitors ambient mic audio (unpublished stream) while agent
  // is speaking. Fires handleInterruptAndSpeak() after 300 ms of sustained
  // speech so the agent audio stops and the user's new turn is recorded.
  useVoiceActivityMonitor({
    active: status === "speaking",
    onSpeech: () => {
      void handleInterruptAndSpeak();
    },
  });

  // ── Text fallback ────────────────────────────────────────────────────────

  const handleSendText = (): void => {
    const text = draft.trim();
    if (!text) return;
    onSendText(text);
    setDraft("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  // ── Voice button — simple toggle ──────────────────────────────────────────
  // ON  → click → OFF: cancel the active or upcoming listen cycle immediately.
  // OFF → click → ON : the auto-restart effect starts recording right away.
  const handleVoiceBtnClick = (): void => {
    if (continuousMode) {
      setContinuousMode(false);
      if (status === "recording") void handleStopRecording();
      // If thinking / speaking: mic is already off; disabling the mode means
      // the effect won't restart it after the agent finishes.
      return;
    }
    // Start continuous mode — works from idle or while agent is speaking.
    setContinuousMode(true);
    // Effect handles recording when status is already idle_in_call.
    // If speaking: barge-in will fire next time the user speaks, and after
    // the interrupted turn completes the cycle self-sustains.
  };

  // ── Derived UI values ────────────────────────────────────────────────────

  // While continuous mode is transitioning between cycles (idle_in_call →
  // mic enable → recording) show "Listening" so the button doesn't flash.
  const voiceBtnLabel = (() => {
    if (status === "recording" || (continuousMode && status === "idle_in_call")) return "Listening";
    if (status === "thinking") return "Sending…";
    if (status === "speaking") return "Speaking";
    return continuousMode ? "Listening" : "Voice";
  })();

  const voiceBtnCls = (() => {
    if (status === "thinking") return "processing";
    if (status === "speaking") return "speaking";
    if (status === "recording" || continuousMode) return "listening";
    return "";
  })();

  // Allow stopping continuous mode at any non-network phase; keep disabled
  // only for actual connection states and while the mic track is initialising.
  const voiceBtnDisabled = mic.starting || status === "connecting" || status === "reconnecting";

  const thinking = status === "thinking";
  const textDisabled = status !== "idle_in_call" && status !== "speaking";

  return (
    <div className="rounded-xl border bg-card p-3.5">
      <div className="flex items-center gap-2.5">
        {/* ── Pill input (always text mode) ── */}
        <div
          className={cn(
            "flex flex-1 items-end gap-2 rounded-full border bg-background px-5 py-2 transition-colors",
            "focus-within:border-primary/40",
          )}
        >
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
        </div>

        {/* ── Voice toggle button ── */}
        <button
          type="button"
          onClick={handleVoiceBtnClick}
          disabled={voiceBtnDisabled}
          aria-pressed={continuousMode}
          aria-label={continuousMode ? "Stop listening" : "Start continuous voice mode"}
          className={cn(
            "inline-flex items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-medium",
            "transition-all duration-200",
            "disabled:cursor-not-allowed disabled:opacity-50",
            voiceBtnCls === "" && "border-border bg-card text-foreground hover:bg-muted",
            voiceBtnCls === "listening" &&
              "border-transparent bg-primary text-primary-foreground shadow-[0_0_0_4px_hsl(var(--primary)/0.18)]",
            voiceBtnCls === "speaking" &&
              "border-transparent bg-violet-500 text-white shadow-[0_0_0_4px_rgb(139_92_246/0.22)]",
            voiceBtnCls === "processing" &&
              "border-transparent bg-amber-500 text-white shadow-[0_0_0_4px_rgb(245_158_11/0.22)]",
          )}
        >
          {voiceBtnCls === "listening" || voiceBtnCls === "speaking" ? (
            <VoiceWaveBars />
          ) : (
            <VoicePulseIcon pulsing={voiceBtnCls === "processing"} />
          )}
          <span>{voiceBtnLabel}</span>
        </button>

        {/* ── Demo confirmation (icon-only) ── */}
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

      {thinking && (
        <p className="mt-2.5 text-center text-xs text-muted-foreground">
          Processing your message&hellip;
        </p>
      )}
    </div>
  );
}

/* ── Small decorative sub-components ── */

function VoicePulseIcon({ pulsing }: { pulsing: boolean }) {
  return (
    <span className="relative flex size-4 items-center justify-center">
      <span
        className={cn(
          "absolute inset-0 animate-ping rounded-full border border-current",
          pulsing ? "opacity-70" : "opacity-60",
        )}
      />
      <span
        className={cn(
          "absolute inset-0 animate-ping rounded-full border border-current [animation-delay:0.6s]",
          pulsing ? "opacity-40" : "opacity-35",
        )}
      />
      <span className="relative size-1.5 rounded-full bg-current" />
    </span>
  );
}

function VoiceWaveBars() {
  return (
    <span className="flex items-center gap-[3px]" aria-hidden>
      {[0, 1, 2, 3, 4].map((i) => (
        <span
          key={i}
          className="w-[2px] rounded-sm bg-current animate-[wavebar_1.1s_ease-in-out_infinite]"
          style={{
            animationDelay: `${i * 0.12}s`,
            height: `${8 + Math.abs(2 - i) * 4}px`,
          }}
        />
      ))}
    </span>
  );
}
