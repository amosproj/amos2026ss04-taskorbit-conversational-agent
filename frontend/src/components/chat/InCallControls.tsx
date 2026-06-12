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
import { ArrowUp, Check, Mic, PhoneOff, UserRoundCog, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useMicRecorder } from "@/hooks/useMicRecorder";
import { useSilenceDetection } from "@/hooks/useSilenceDetection";
import { useVoiceActivityMonitor } from "@/hooks/useVoiceActivityMonitor";
import { fetchUserAgents } from "@/lib/userAgentsApi";
import type { CallStatus } from "@/types/callState";

type RoutingTarget = { id: string; name: string };

const AGENT_COLORS = [
  "oklch(0.66 0.18 295)", // purple
  "oklch(0.68 0.16 245)", // blue
  "oklch(0.74 0.15 162)", // green
];

type Props = {
  status: CallStatus;
  /** When true the mic button is locked out — used while the greeting is playing. */
  greetingInProgress?: boolean;
  onPhase: (phase: CallStatus) => void;
  onEnd: () => void;
  onSendText: (
    text: string,
    manualTransfer?: { target_agent_id: string; target_agent_name: string } | null,
  ) => void;
  /** Fires immediately when the user picks (or clears) an agent from the @route menu. */
  onRoutingTargetChange?: (target: { id: string; name: string } | null) => void;
  onTriggerConfirmation: () => void;
  onMicError: (message: string | null) => void;
};

export function InCallControls({
  status,
  greetingInProgress = false,
  onPhase,
  onEnd,
  onSendText,
  onRoutingTargetChange,
  onTriggerConfirmation: _onTriggerConfirmation,
  onMicError,
}: Props) {
  const mic = useMicRecorder();
  const [draft, setDraft] = useState("");
  const [continuousMode, setContinuousMode] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const inputId = useId();

  // ── Agent routing ────────────────────────────────────────────────────────
  const [routingTarget, setRoutingTarget] = useState<RoutingTarget | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [agents, setAgents] = useState<RoutingTarget[]>([]);
  const [menuFilter, setMenuFilter] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);
  const atMentionStartRef = useRef<number | null>(null);

  // Fetch agents once when menu first opens
  const loadAgents = async () => {
    if (agents.length > 0) return;
    try {
      const entries = await fetchUserAgents();
      setAgents(entries.map((e) => ({ id: e.id, name: e.name })));
    } catch {
      // silently ignore — menu stays empty
    }
  };

  const openMenu = () => {
    void loadAgents();
    setMenuFilter("");
    setMenuOpen(true);
  };

  const selectAgent = (agent: RoutingTarget) => {
    setRoutingTarget(agent);
    onRoutingTargetChange?.(agent);
    setMenuOpen(false);
    // Remove any trailing @-mention text from draft
    if (atMentionStartRef.current !== null) {
      setDraft((d) => d.slice(0, atMentionStartRef.current!));
      atMentionStartRef.current = null;
    }
    textareaRef.current?.focus();
  };

  const clearRouting = () => {
    setRoutingTarget(null);
    onRoutingTargetChange?.(null);
    setMenuOpen(false);
    atMentionStartRef.current = null;
  };

  // Close menu on outside click
  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
        atMentionStartRef.current = null;
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [menuOpen]);

  const filteredAgents = agents.filter((a) =>
    a.name.toLowerCase().includes(menuFilter.toLowerCase()),
  );

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
    // Fire interrupt concurrently — don't await before enabling the mic.
    void mic.sendInterrupt();
    try {
      await mic.enable();
      onPhase("recording");
    } catch {
      // mic.error surfaced by useMicRecorder.
    }
  };

  // ── Stable refs so effects never capture stale closures ────────────────

  const handleStartRecordingRef = useRef(handleStartRecording);
  handleStartRecordingRef.current = handleStartRecording;

  const handleStopRecordingRef = useRef(handleStopRecording);
  handleStopRecordingRef.current = handleStopRecording;

  // ── Continuous-mode auto-restart ─────────────────────────────────────────
  // After each agent turn (speaking → idle_in_call), automatically re-enable
  // the mic so the user can speak without pressing anything.
  useEffect(() => {
    if (!continuousMode) return;
    if (status !== "idle_in_call") return;
    void handleStartRecordingRef.current();
  }, [status, continuousMode]);

  // ── Greeting completion auto-start ───────────────────────────────────────
  // When the greeting finishes playing, automatically enter continuous mode
  // and start recording so the user can respond without having to tap anything.
  const greetingWasActiveRef = useRef(false);
  if (greetingInProgress) greetingWasActiveRef.current = true;

  useEffect(() => {
    if (greetingInProgress) return;
    if (!greetingWasActiveRef.current) return; // component mounted after greeting already done
    greetingWasActiveRef.current = false;
    // Only enable the mode — the auto-restart effect above will call
    // handleStartRecording once status reaches idle_in_call. Calling
    // handleStartRecording here can race against the LiveKit room not
    // being fully connected yet (publishing track {room: undefined}).
    setContinuousMode(true);
  }, [greetingInProgress]);

  // ── Greeting mic lock ────────────────────────────────────────────────────
  // Ensure the mic is off for the entire duration of the greeting. The
  // button is already visually disabled, but this guard handles any race
  // where the mic was open before greetingInProgress became true.
  useEffect(() => {
    if (!greetingInProgress) return;
    void mic.disable();
  }, [greetingInProgress, mic]);

  // ── Barge-in mic pre-warm ────────────────────────────────────────────────
  // Publish the mic as soon as the agent starts speaking so Deepgram is
  // already receiving audio before the user decides to interrupt.
  // Without this, the user's first words are always missed because
  // enable() cold-starts the OS hardware (300–500 ms latency).
  // The backend's allow_interruptions=True handles the actual interruption;
  // the frontend VAD (useVoiceActivityMonitor) just sends the explicit
  // interrupt signal to stop TTS quickly.
  useEffect(() => {
    if (!continuousMode) return;
    if (greetingInProgress) return;
    if (status !== "speaking") return;
    if (mic.enabled || mic.starting) return;
    void mic.enable();
  }, [status, continuousMode, greetingInProgress, mic]);

  // ── No-speech timeout ────────────────────────────────────────────────────
  // If the mic is open but the user never speaks (amplitude stays below the
  // speech floor for NO_SPEECH_MS), mute back to idle_in_call automatically.
  // This handles the "agent is waiting, user says nothing" case. Distinct from
  // silence detection which fires only after the user starts then pauses.
  useEffect(() => {
    if (status !== "recording") return;
    const SPEECH_FLOOR = 45;
    const NO_SPEECH_MS = 10000;
    const start = Date.now();
    let hasSpeech = false;
    const id = setInterval(() => {
      const levels = mic.levelsRef.current;
      const avg = levels.reduce((s, v) => s + v, 0) / (levels.length || 1);
      if (avg >= SPEECH_FLOOR) {
        hasSpeech = true;
        clearInterval(id);
        return;
      }
      if (!hasSpeech && Date.now() - start >= NO_SPEECH_MS) {
        clearInterval(id);
        setContinuousMode(false);
        void handleStopRecordingRef.current();
      }
    }, 100);
    return () => clearInterval(id);
  }, [status, mic.levelsRef]);

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
  // Disabled during the greeting so ambient noise can't interrupt it.
  useVoiceActivityMonitor({
    active: status === "speaking" && !greetingInProgress && continuousMode,
    onSpeech: () => {
      void handleInterruptAndSpeak();
    },
  });

  // ── Text fallback ────────────────────────────────────────────────────────

  const handleSendText = (): void => {
    const text = draft.trim();
    if (!text) return;
    const transfer = routingTarget
      ? { target_agent_id: routingTarget.id, target_agent_name: routingTarget.name }
      : null;
    onSendText(text, transfer);
    setDraft("");
    setRoutingTarget(null);
    atMentionStartRef.current = null;
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  // ── Voice button — simple toggle ──────────────────────────────────────────
  // ON  → click → OFF: cancel the active or upcoming listen cycle immediately.
  // OFF → click → ON : the auto-restart effect starts recording right away.
  const handleVoiceBtnClick = (): void => {
    if (continuousMode) {
      setContinuousMode(false);
      if (status === "recording") {
        void handleStopRecording(); // disables mic + sets idle_in_call
      } else {
        // Mic may be open from the pre-warm effect (speaking phase) or a
        // previous recording phase — disable it regardless of current status.
        void mic.disable();
        if (status !== "speaking") {
          onPhase("idle_in_call");
        }
      }
      return;
    }
    // Start continuous mode — works from idle or while agent is speaking.
    setContinuousMode(true);
    // Effect handles recording when status is already idle_in_call.
  };

  // ── Derived UI values ────────────────────────────────────────────────────

  const voiceBtnCls = (() => {
    if (status === "thinking") return "processing";
    if (status === "speaking" && continuousMode) return "speaking";
    if (status === "recording" || continuousMode) return "listening";
    return "";
  })();

  const thinking = status === "thinking";
  const awaitingConfirmation = status === "awaiting_confirmation";
  const textDisabled = awaitingConfirmation || (status !== "idle_in_call" && status !== "speaking");

  // Allow stopping continuous mode at any non-network phase; keep disabled
  // only for actual connection states and while the mic track is initialising.
  const voiceBtnDisabled =
    greetingInProgress ||
    mic.starting ||
    status === "connecting" ||
    status === "reconnecting" ||
    awaitingConfirmation;

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
            placeholder={
              awaitingConfirmation
                ? "Approve or deny the action above to continue…"
                : "Ask from Orbit."
            }
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

        {/* ── Mic toggle button ── */}
        <button
          type="button"
          onClick={handleVoiceBtnClick}
          disabled={voiceBtnDisabled}
          aria-pressed={continuousMode}
          aria-label={continuousMode ? "Stop listening" : "Start voice mode"}
          className={cn(
            "flex size-11 shrink-0 items-center justify-center rounded-full border",
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
            <Mic size={18} />
          )}
        </button>

        {/* ── Agent routing button + dropdown ── */}
        <div className="relative shrink-0">
          {menuOpen && (
            <div
              ref={menuRef}
              className="absolute bottom-full right-0 mb-2 z-50 w-56 rounded-xl border bg-popover shadow-lg py-1.5"
            >
              <p className="px-3 py-1 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                Route to agent
              </p>
              {filteredAgents.length === 0 ? (
                <p className="px-3 py-2 text-xs text-muted-foreground">No agents found</p>
              ) : (
                filteredAgents.map((a, i) => (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => selectAgent(a)}
                    className="flex w-full items-center gap-2.5 px-3 py-2 text-sm hover:bg-muted transition-colors"
                  >
                    <span
                      className="size-2.5 shrink-0 rounded-full"
                      style={{ background: AGENT_COLORS[i % AGENT_COLORS.length] }}
                    />
                    <span className="flex-1 truncate text-left">{a.name}</span>
                    {routingTarget?.id === a.id && (
                      <Check size={13} className="shrink-0 text-primary" />
                    )}
                  </button>
                ))
              )}
              {routingTarget && (
                <>
                  <div className="my-1 border-t" />
                  <button
                    type="button"
                    onClick={clearRouting}
                    className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors"
                  >
                    <X size={13} className="shrink-0" />
                    Clear routing
                  </button>
                </>
              )}
            </div>
          )}
          <button
            type="button"
            onClick={openMenu}
            disabled={status !== "idle_in_call"}
            aria-label="Route to agent"
            title={routingTarget ? `Routed to ${routingTarget.name}` : "Route to agent"}
            className={cn(
              "flex size-11 shrink-0 items-center justify-center rounded-full border transition-all",
              "disabled:cursor-not-allowed disabled:opacity-40",
              routingTarget
                ? "border-transparent text-white"
                : "border-border bg-card text-foreground hover:bg-muted",
            )}
            style={
              routingTarget && status === "idle_in_call"
                ? { background: AGENT_COLORS[0] }
                : undefined
            }
          >
            <UserRoundCog size={16} />
          </button>
        </div>

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
