import { LiveKitRoom, RoomAudioRenderer } from "@livekit/components-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { AgentIdentityCard } from "@/components/chat/AgentIdentityCard";
import { CallControls } from "@/components/chat/CallControls";
import { CallStatusIndicator } from "@/components/chat/CallStatusIndicator";
import { ConfirmationPrompt } from "@/components/chat/ConfirmationPrompt";
import { InCallControls } from "@/components/chat/InCallControls";
import { PreCallDiagnostics } from "@/components/chat/PreCallDiagnostics";
import { VoiceSessionBridge } from "@/components/chat/VoiceSessionBridge";
import { TranscriptBubble } from "@/components/history/TranscriptBubble";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useVoiceCall } from "@/hooks/useVoiceCall";
import type { TranscriptionSegment } from "@/hooks/useAgentTranscription";
import { useActiveAgent } from "@/components/active-agent-provider";
import { buildLiveKitWorkerMetadata } from "@/lib/livekitAgentMetadata";
import { sendMessage, sendMessageStream, getConversations } from "@/lib/conversationApi";
import { playSynthesizedSpeech } from "@/lib/ttsApi";
import { backendToFrontendAgent, fetchUserAgents, type UserAgentEntry } from "@/lib/userAgentsApi";
import type { LiveTranscriptTurn } from "@/types/callState";

function findUserAgentEntry(
  entries: UserAgentEntry[],
  agentKey: string,
): UserAgentEntry | undefined {
  return entries.find(
    (e) => e.template_id === agentKey || e.id === agentKey || e.config.id === agentKey,
  );
}

// Tidy up common Deepgram artefacts in user transcription before display.
// Runs at render time only — does not mutate stored state.
function normaliseUserText(text: string): string {
  // Lowercase email domains: Bob@Gmail.com → Bob@gmail.com
  let out = text.replace(
    /(@)([A-Za-z0-9.-]+\.[A-Za-z]{2,})/g,
    (_, at, domain) => at + domain.toLowerCase(),
  );
  // Collapse individually-dictated digits: "2 6 7 8" → "2678" (loop until stable)
  let prev: string;
  do {
    prev = out;
    out = out.replace(/(\d) (\d)/g, "$1$2");
  } while (out !== prev);
  // "2678 plus 1" → "2678+1"
  out = out.replace(/(\d+)\s+plus\s+(\d)/gi, "$1+$2");
  return out;
}

function SessionEndedBanner({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  useEffect(() => {
    const id = window.setTimeout(onDismiss, 5_000);
    return () => window.clearTimeout(id);
  }, [onDismiss]);

  return (
    <div
      role="status"
      className="fixed bottom-4 left-1/2 -translate-x-1/2 rounded-lg border border-amber-500 bg-amber-50 px-4 py-3 text-sm text-amber-800 shadow-md dark:bg-amber-950 dark:text-amber-200"
    >
      {message}
    </div>
  );
}

/**
 * Live call surface for the Meisterwerk-customer end of the agent
 * pipeline. Drives a `CallStatus` state machine fed by:
 *
 * 1. `useVoiceCall` — token fetch, conversation id, transcript array,
 *    pre/post-call lifecycle.
 * 2. `VoiceSessionBridge` — translates LiveKit events (agent state,
 *    transcription streams, connection drops) into phase changes.
 * 3. `InCallControls` — mic publish/mute, Stop/Send, end call.
 *
 * Audio out: LiveKit agent TTS is played by `RoomAudioRenderer`. Typed
 * replies use `POST /v1/tts/synthesize` (ElevenLabs) so the assistant
 * answer is still heard when the user uses the text disclosure.
 */
export function ConversationalChat() {
  // Active agent comes from shared context, set on the config page. Before
  // this hook existed, the chat was hardcoded to JOHN_DOE_AGENT — Christoph
  // + Carl reported the bug on Discord 2026-05-24.
  // setActiveAgent is used below to swap the displayed agent when the backend
  // signals an agent_transfer via response.tool_invoked (#8 Task 6).
  const { agent, setActiveAgent } = useActiveAgent();
  const appName = import.meta.env.VITE_APP_NAME ?? "TaskOrbit";

  const call = useVoiceCall();
  // Tracks whether the agent's opening greeting has finished playing.
  // Starts true (no call active). Set false on call start, then back to
  // true once the first speaking→idle_in_call transition is detected.
  const [greetingDone, setGreetingDone] = useState(true);
  const [agentMuted, setAgentMuted] = useState(false);
  const [routedAgent, setRoutedAgent] = useState<string | null>(null);
  // Stable ref so async playback closures always read the current mute state.
  const agentVolumeRef = useRef(1);
  useEffect(() => {
    agentVolumeRef.current = agentMuted ? 0 : 1;
  }, [agentMuted]);
  // When the user manually routes via the @chip, lock out voice-based routing
  // overrides until the manual routing is cleared or the session restarts.
  const manualRoutingLockRef = useRef(false);
  const greetingSeenSpeakingRef = useRef(false);
  const greetingTimeoutRef = useRef<number | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const lastUserTurnIdRef = useRef<string | null>(null);
  const lockedIntentRef = useRef<string | null>(null);
  const pendingConfirmationIdRef = useRef<string | null>(null);
  const [completedWorkflowSteps, setCompletedWorkflowSteps] = useState<string[]>([]);
  const [previousConversations, setPreviousConversations] = useState<
    Record<string, string | null>[]
  >([]);

  // Load previous conversations on page load (reload restores conversations)
  useEffect(() => {
    const loadConversations = async () => {
      try {
        const data = await getConversations();
        setPreviousConversations(data.conversations || []);
      } catch (error) {
        console.error("Failed to load conversations:", error);
      }
    };
    loadConversations();
  }, []);

  // Agent segment merging: livekit-agents emits one stream per TTS chunk,
  // each with a unique lk.segment_id. We collapse them into a single turn
  // (agentTurnIdRef) so the bubble grows instead of spawning new bubbles.
  const agentTurnIdRef = useRef<string | null>(null);
  const agentCommittedRef = useRef<string>("");
  const agentActiveSegRef = useRef<string | null>(null);

  // Merge consecutive user turns into one bubble (display only — raw state
  // is unchanged). Also applies normaliseUserText so email/digit artefacts
  // are cleaned up without touching the stored transcript.
  const mergedTranscript = useMemo<LiveTranscriptTurn[]>(() => {
    const result: LiveTranscriptTurn[] = [];
    for (const turn of call.transcript) {
      const last = result[result.length - 1];
      if (turn.role === "user" && last?.role === "user") {
        result[result.length - 1] = {
          ...last,
          text: normaliseUserText(`${last.text} ${turn.text}`.trim()),
          isFinal: turn.isFinal,
        };
      } else {
        result.push(turn.role === "user" ? { ...turn, text: normaliseUserText(turn.text) } : turn);
      }
    }
    return result;
  }, [call.transcript]);

  // Keep transcript rendering anchored to the latest turn.
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [call.transcript]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (greetingTimeoutRef.current !== null) clearTimeout(greetingTimeoutRef.current);
    };
  }, []);

  // Reset mute state between calls so a new session is never silently muted.
  useEffect(() => {
    if (call.status === "idle" || call.status === "ended") {
      setAgentMuted(false);
    }
  }, [call.status]);

  // Detect greeting completion: first speaking → idle_in_call transition after
  // a call starts. Unlocks the mic button and triggers continuous mode.
  useEffect(() => {
    if (greetingDone) return;
    if (call.status === "speaking") {
      greetingSeenSpeakingRef.current = true;
      return;
    }
    if (call.status === "idle_in_call" && greetingSeenSpeakingRef.current) {
      greetingSeenSpeakingRef.current = false;
      if (greetingTimeoutRef.current !== null) {
        clearTimeout(greetingTimeoutRef.current);
        greetingTimeoutRef.current = null;
      }
      setGreetingDone(true);
    }
  }, [call.status, greetingDone]);

  const handleSegment = useCallback(
    (segment: TranscriptionSegment) => {
      // console.log("[greeting] handleSegment:", segment.role, segment.id, JSON.stringify(segment.text).slice(0, 60), "final:", segment.isFinal);
      if (segment.role === "user") {
        // A new user turn resets the agent turn context for the next response.
        agentTurnIdRef.current = null;
        agentCommittedRef.current = "";
        agentActiveSegRef.current = null;

        lastUserTurnIdRef.current = segment.id;
        call.upsertTurnById(segment.id, "user", segment.text, segment.isFinal);
        return;
      }

      if (segment.isFinal) {
        if (segment.text.toLowerCase().includes("i didn't get your message")) {
          if (lastUserTurnIdRef.current) {
            call.removeTurnById(lastUserTurnIdRef.current);
            lastUserTurnIdRef.current = null;
          }
        } else {
          lastUserTurnIdRef.current = null;
        }
      }

      // Ensure a stable turn ID exists for this agent response.
      if (agentTurnIdRef.current === null) {
        agentTurnIdRef.current = segment.id;
        agentActiveSegRef.current = segment.id;
      }

      // A new lk.segment_id means a new TTS chunk started. The previous chunk
      // should have already been committed when its isFinal fired.
      if (segment.id !== agentActiveSegRef.current) {
        agentActiveSegRef.current = segment.id;
      }

      // Merged text = all previously finalized chunks + live text of the current chunk.
      const prefix = agentCommittedRef.current;
      const mergedText = prefix ? `${prefix} ${segment.text}` : segment.text;

      call.upsertTurnById(agentTurnIdRef.current, "assistant", mergedText.trim(), segment.isFinal);

      // Once this chunk is final, grow the committed base for the next chunk.
      if (segment.isFinal) {
        agentCommittedRef.current = mergedText.trim();
      }
    },
    [call],
  );

  const handleSendText = useCallback(
    (
      text: string,
      manualTransfer?: { target_agent_id: string; target_agent_name: string } | null,
    ) => {
      let convId = call.conversationId;
      // If the user starts a session via the "Use text instead" input rather than the
      // "Start session" button, the UI state is still 'idle'. We must explicitly
      // initialize the session here (which transitions the UI and generates an ID)
      // before dispatching the message.
      if (call.status === "idle") {
        lockedIntentRef.current = null;
        manualRoutingLockRef.current = false;
        setRoutedAgent(null);
        setCompletedWorkflowSteps([]);
        pendingConfirmationIdRef.current = null;
        convId = call.start({
          tokenMetadata: buildLiveKitWorkerMetadata(agent),
          greeting: agent.first_message.message || undefined,
        });
      }

      call.appendUserTurn(text);
      call.setPhase("thinking");

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      void Promise.resolve().then(async () => {
        const assistantTurnId = `assistant-stream-${Date.now()}`;
        let replyText = "";

        try {
          const stream = sendMessageStream(
            agent,
            [...call.transcript, { id: "tmp", role: "user", text }],
            convId,
            controller.signal,
            lockedIntentRef.current,
            null,
            null,
            completedWorkflowSteps,
            routedAgent,
            manualTransfer ?? null,
          );

          for await (const event of stream) {
            if (event.type === "chunk") {
              replyText += event.text;
              call.upsertTurnById(assistantTurnId, "assistant", replyText, false);
            } else if (event.type === "done") {
              call.upsertTurnById(assistantTurnId, "assistant", replyText, true);

              if (event.conversation_id) call.updateConversationId(event.conversation_id);
              lockedIntentRef.current = event.locked_intent_name ?? null;
              setCompletedWorkflowSteps(event.completed_workflow_steps ?? []);

              if (!manualTransfer && event.selected_agent) {
                setRoutedAgent(event.selected_agent);
                if (event.selected_agent !== agent.agent_id && !manualRoutingLockRef.current) {
                  const entries = await fetchUserAgents(controller.signal);
                  const match = findUserAgentEntry(entries, event.selected_agent);
                  if (match) {
                    const next = backendToFrontendAgent(match);
                    setActiveAgent(next, `ua:${match.template_id ?? match.id}`);
                  }
                }
              }

              if (
                (event.status === "confirmation_required" ||
                  event.status === "workflow_confirmation_required") &&
                event.confirmation
              ) {
                pendingConfirmationIdRef.current = event.confirmation.confirmation_id;
                call.triggerConfirmation({
                  ...event.confirmation,
                  type: event.status === "workflow_confirmation_required" ? "workflow" : "tool",
                });
                return;
              }

              // Manual transfer: swap active agent config after backend confirmation.
              // The transcript announcement was already appended in handleRoutingTargetChange.
              if (manualTransfer?.target_agent_id && event.status !== "error") {
                const badgeName = manualTransfer.target_agent_name
                  .replace(/\s+[Aa]gent$/i, "")
                  .trim();
                manualRoutingLockRef.current = true;
                setRoutedAgent(badgeName);
                try {
                  const entries = await fetchUserAgents(controller.signal);
                  const match = entries.find(
                    (e) =>
                      e.id === manualTransfer.target_agent_id ||
                      e.template_id === manualTransfer.target_agent_id,
                  );
                  if (match) {
                    const next = backendToFrontendAgent(match);
                    setActiveAgent(next, `ua:${match.template_id ?? match.id}`);
                  } else {
                    call.appendAssistantTurn(
                      `[Could not transfer to ${manualTransfer.target_agent_name}]`,
                    );
                    setRoutedAgent(null);
                    manualRoutingLockRef.current = false;
                  }
                } catch (transferErr) {
                  if ((transferErr as Error).name !== "AbortError") {
                    call.appendAssistantTurn(
                      `[Could not transfer to ${manualTransfer.target_agent_name}]`,
                    );
                    setRoutedAgent(null);
                    manualRoutingLockRef.current = false;
                  }
                }
              }

              if (event.status === "ended") {
                if (replyText) {
                  await playSynthesizedSpeech(replyText, {
                    signal: controller.signal,
                    volumeRef: agentVolumeRef,
                  }).catch(() => {});
                }
                call.end();
                return;
              }

              // Agent handoff (#8 Task 6): backend's IntentRouter / dispatch decided
              // to transfer the conversation. Swap the displayed agent and add a
              // transcript marker so the user sees the switch.
              if (!manualTransfer && event.tool_invoked?.type === "agent_transfer") {
                const targets = (event.tool_invoked.parameters as { targets?: string[] })?.targets;
                const targetId = targets?.[0];
                if (targetId) {
                  try {
                    const entries = await fetchUserAgents(controller.signal);
                    const match = entries.find(
                      (e) => e.template_id === targetId || e.id === targetId,
                    );
                    if (match) {
                      const next = backendToFrontendAgent(match);
                      setActiveAgent(next, `ua:${match.template_id ?? match.id}`);
                      call.appendAssistantTurn(`[Transferred to ${next.name}]`);
                    }
                  } catch (transferErr) {
                    if ((transferErr as Error).name !== "AbortError") {
                      console.warn(
                        "[ConversationalChat] agent transfer lookup failed",
                        transferErr,
                      );
                    }
                  }
                }
              }
            } else if (event.type === "error") {
              call.upsertTurnById(assistantTurnId, "assistant", `[Error: ${event.message}]`, true);
            }
          }

          const speakable =
            replyText.trim().length > 0 && !replyText.startsWith("[Connection error");
          if (speakable) {
            call.setPhase("speaking");
            try {
              await playSynthesizedSpeech(replyText, {
                signal: controller.signal,
                volumeRef: agentVolumeRef,
              });
            } catch (audioErr) {
              if ((audioErr as Error).name !== "AbortError") {
                console.warn("[ConversationalChat] ElevenLabs playback failed", audioErr);
              }
            }
          }
          call.setPhase("idle_in_call");
        } catch (err) {
          if ((err as Error).name === "AbortError") return;
          call.upsertTurnById(
            assistantTurnId,
            "assistant",
            `[Connection error: ${(err as Error).message}]`,
            true,
          );
          call.setPhase("idle_in_call");
        }
      });
    },
    [agent, call, setActiveAgent],
  );

  const handleRoomError = useCallback(
    (err: Error) => {
      if (err.name === "NotAllowedError" || err.message.includes("Permission")) {
        call.setMicError(
          "Microphone access was denied. Please allow microphone access to use voice.",
        );
      }
    },
    [call],
  );

  // AC7: when the voice worker publishes an agent_handoff packet (after
  // the orchestrator dispatched agent_transfer mid-call), useAgentHandoff
  // already swapped the active agent. Surface the same transcript marker
  // the text path renders so the user sees the switch.
  const handleVoiceHandoff = useCallback(
    (agentName: string) => {
      call.appendAssistantTurn(`[Transferred to ${agentName}]`);
    },
    [call],
  );

  const handleVoiceAgentRouted = useCallback((agentName: string) => {
    if (manualRoutingLockRef.current) return;
    setRoutedAgent(agentName);
  }, []);

  // Fires the moment the user picks an agent from the route dropdown.
  // Shows the transcript announcement and speaks it immediately so the user
  // gets visual + audio feedback on selection. setActiveAgent is intentionally
  // NOT called here — the config swap happens in handleSendText after backend
  // confirmation to avoid swapping before the turn is actually sent.
  const handleRoutingTargetChange = useCallback(
    (target: { id: string; name: string } | null) => {
      if (!target) {
        manualRoutingLockRef.current = false;
        setRoutedAgent(null);
        return;
      }
      const badgeName = target.name.replace(/\s+[Aa]gent$/i, "").trim();
      manualRoutingLockRef.current = true;
      setRoutedAgent(badgeName);
      const transferMsg = `Transferring you to ${target.name} upon your request.`;
      call.appendAssistantTurn(transferMsg);
      playSynthesizedSpeech(transferMsg).catch(() => {});
    },
    [call],
  );

  const handleTriggerConfirmation = useCallback(() => {
    // Confirmation is triggered by the backend response, not a UI button.
  }, []);

  const handleSendDecision = useCallback(
    (confirmationId: string, decision: "confirm" | "reject") => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      void Promise.resolve().then(async () => {
        try {
          const response = await sendMessage(
            agent,
            call.transcript,
            call.conversationId,
            controller.signal,
            lockedIntentRef.current,
            confirmationId,
            decision,
            completedWorkflowSteps,
            routedAgent,
          );
          call.updateConversationId(response.conversation_id);
          lockedIntentRef.current = response.locked_intent_name ?? null;
          setCompletedWorkflowSteps(response.completed_workflow_steps ?? []);

          if (response.selected_agent) {
            setRoutedAgent(response.selected_agent);
            if (response.selected_agent !== agent.agent_id && !manualRoutingLockRef.current) {
              const entries = await fetchUserAgents(controller.signal);
              const match = findUserAgentEntry(entries, response.selected_agent);
              if (match) {
                const next = backendToFrontendAgent(match);
                setActiveAgent(next, `ua:${match.template_id ?? match.id}`);
              }
            }
          }

          if (
            (response.status === "confirmation_required" ||
              response.status === "workflow_confirmation_required") &&
            response.confirmation
          ) {
            pendingConfirmationIdRef.current = response.confirmation.confirmation_id;
            call.triggerConfirmation({
              ...response.confirmation,
              type: response.status === "workflow_confirmation_required" ? "workflow" : "tool",
            });
            return;
          }

          const replyText = response.reply.content;
          call.appendAssistantTurn(replyText);
          const speakable =
            replyText.trim().length > 0 && !replyText.startsWith("[Connection error");
          if (speakable) {
            call.setPhase("speaking");
            try {
              await playSynthesizedSpeech(replyText, {
                signal: controller.signal,
                volumeRef: agentVolumeRef,
              });
            } catch (audioErr) {
              if ((audioErr as Error).name !== "AbortError") {
                console.warn("[ConversationalChat] ElevenLabs playback failed", audioErr);
              }
            }
          }
        } catch (err) {
          if ((err as Error).name === "AbortError") return;
          call.appendAssistantTurn(`[Connection error: ${(err as Error).message}]`);
        } finally {
          // Restore the idle UI state only if we aren't immediately blocked by another confirmation.
          if (pendingConfirmationIdRef.current === null) {
            call.setPhase("idle_in_call");
          }
        }
      });
    },
    [agent, call, completedWorkflowSteps, routedAgent, setActiveAgent],
  );

  const handleApprove = useCallback(() => {
    const confirmId = pendingConfirmationIdRef.current;
    if (confirmId === null) return;
    pendingConfirmationIdRef.current = null;
    call.approveConfirmation();
    handleSendDecision(confirmId, "confirm");
  }, [call, handleSendDecision]);

  const handleDeny = useCallback(() => {
    const confirmId = pendingConfirmationIdRef.current;
    if (confirmId === null) return;
    pendingConfirmationIdRef.current = null;
    call.denyConfirmation();
    handleSendDecision(confirmId, "reject");
  }, [call, handleSendDecision]);

  const handleRestart = useCallback(() => {
    lockedIntentRef.current = null;
    manualRoutingLockRef.current = false;
    pendingConfirmationIdRef.current = null;
    setRoutedAgent(null);
    setCompletedWorkflowSteps([]);
    call.restart();
  }, [call]);

  const handleStartSession = useCallback(() => {
    // console.log("[greeting] handleStartSession fired");
    lockedIntentRef.current = null;
    pendingConfirmationIdRef.current = null;
    setRoutedAgent(null);
    setCompletedWorkflowSteps([]);
    call.start({ tokenMetadata: buildLiveKitWorkerMetadata(agent) });
    setGreetingDone(false);
    greetingSeenSpeakingRef.current = false;
    if (greetingTimeoutRef.current !== null) clearTimeout(greetingTimeoutRef.current);
    greetingTimeoutRef.current = window.setTimeout(() => {
      greetingTimeoutRef.current = null;
      setGreetingDone(true);
    }, 15_000);
  }, [agent, call]);

  const isPreCall = call.status === "idle";
  const isPostCall = call.status === "ended";
  const isInCall = !isPreCall && !isPostCall;

  const body: ReactNode = (
    <div className="mx-auto flex min-h-svh max-w-2xl flex-col gap-6 px-4 py-8 sm:px-6 sm:py-10">
      <header className="space-y-1">
        <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
          Conversational agent
        </p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{appName}</h1>
        <p className="text-sm text-muted-foreground">
          I'm here to help with your needs. Start chatting by sending a message or using the mic
          button to speak.
        </p>
      </header>

      {previousConversations.length > 0 && isPreCall && (
        <Card>
          <CardHeader>
            <CardTitle>Previous Conversations</CardTitle>
            <CardDescription>
              You have {previousConversations.length} previous conversation
              {previousConversations.length !== 1 ? "s" : ""}. Start a new call to continue.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {isPreCall ? (
        <>
          <AgentIdentityCard agent={agent} />
          <PreCallDiagnostics />
        </>
      ) : null}

      {isInCall ? (
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3 border-b">
            <div className="space-y-1">
              <CardTitle>{agent.name}</CardTitle>
              <CardDescription>
                {call.status === "connecting"
                  ? "Connecting to your agent…"
                  : "Voice session active · live transcript below."}
              </CardDescription>
            </div>
            <div className="flex flex-col items-end gap-2">
              <CallStatusIndicator status={call.status} />
              {routedAgent && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
                  <span className="size-1.5 rounded-full bg-primary" />
                  {routedAgent.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())} Agent
                </span>
              )}
            </div>
          </CardHeader>
          <CardContent className="pt-6">
            <ScrollArea className="h-[min(50vh,28rem)] pr-3">
              {call.status === "connecting" ? (
                <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                  Waiting for agent to join…
                </div>
              ) : (
                <ul className="flex flex-col gap-4" aria-label="Transcript">
                  {mergedTranscript.map((turn) => (
                    <TranscriptBubble key={turn.id} turn={turn} />
                  ))}
                  <div ref={transcriptEndRef} className="h-px" aria-hidden />
                </ul>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      ) : null}

      {isPostCall ? (
        <Card>
          <CardHeader>
            <CardTitle>Call ended</CardTitle>
            <CardDescription>
              {mergedTranscript.length > 0
                ? `${mergedTranscript.length} turn${mergedTranscript.length === 1 ? "" : "s"} recorded.`
                : "No turns recorded."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[min(40vh,24rem)] pr-3">
              <ul className="flex flex-col gap-4" aria-label="Transcript">
                {mergedTranscript.map((turn) => (
                  <TranscriptBubble key={turn.id} turn={turn} history />
                ))}
              </ul>
            </ScrollArea>
          </CardContent>
        </Card>
      ) : null}

      {isInCall && call.livekitCredentials !== null ? (
        // Wrapper for the bottom UI controls. We keep this sticky to the bottom of the viewport
        // so that the confirmation prompt overlays the input area, preventing the UI from shifting
        // dramatically when a critical action requires approval.
        <div className="sticky bottom-0 z-10 -mx-4 flex flex-col gap-3 bg-background/95 px-4 pb-4 pt-2 backdrop-blur supports-[backdrop-filter]:bg-background/80 sm:-mx-6 sm:px-6">
          {call.confirmation !== null ? (
            <ConfirmationPrompt
              prompt={call.confirmation}
              onApprove={handleApprove}
              onDeny={handleDeny}
            />
          ) : null}
          <InCallControls
            status={call.status}
            greetingInProgress={!greetingDone}
            onPhase={call.setPhase}
            onEnd={call.end}
            onSendText={handleSendText}
            onRoutingTargetChange={handleRoutingTargetChange}
            onTriggerConfirmation={handleTriggerConfirmation}
            onMicError={call.setMicError}
            agentMuted={agentMuted}
            onAgentMutedChange={setAgentMuted}
          />
        </div>
      ) : isInCall ? null : (
        <CallControls
          status={call.status}
          onStart={handleStartSession}
          onSendText={handleSendText}
          onRestart={handleRestart}
        />
      )}
    </div>
  );

  return (
    <main className="min-h-svh bg-background text-foreground">
      {call.livekitCredentials !== null ? (
        <LiveKitRoom
          serverUrl={call.livekitCredentials.url}
          token={call.livekitCredentials.token}
          connect
          audio={false}
          video={false}
          onError={handleRoomError}
        >
          <RoomAudioRenderer volume={agentMuted ? 0 : 1} />
          <VoiceSessionBridge
            status={call.status}
            onPhase={call.setPhase}
            onSegment={handleSegment}
            onHandoff={handleVoiceHandoff}
            onAgentRouted={handleVoiceAgentRouted}
            onSessionEnded={call.end}
          />
          {body}
        </LiveKitRoom>
      ) : (
        body
      )}

      {call.micError !== null && (
        <div
          role="alert"
          className="fixed bottom-4 left-1/2 -translate-x-1/2 rounded-lg border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive shadow-md"
        >
          {call.micError}
        </div>
      )}

      {call.sessionEndReason !== null && (
        <SessionEndedBanner
          message={call.sessionEndReason}
          onDismiss={call.clearSessionEndReason}
        />
      )}
    </main>
  );
}
