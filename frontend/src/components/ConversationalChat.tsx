import { LiveKitRoom, RoomAudioRenderer } from "@livekit/components-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { AgentIdentityCard } from "@/components/chat/AgentIdentityCard";
import { AgentSwitcher } from "@/components/chat/AgentSwitcher";
import { CallControls } from "@/components/chat/CallControls";
import { CallStatusIndicator } from "@/components/chat/CallStatusIndicator";
import { ConfirmationPrompt } from "@/components/chat/ConfirmationPrompt";
import { InCallControls } from "@/components/chat/InCallControls";
import { PreCallDiagnostics } from "@/components/chat/PreCallDiagnostics";
import {
  RecentConversations,
  type RecentConversation,
} from "@/components/chat/RecentConversations";
import { VoiceSessionBridge } from "@/components/chat/VoiceSessionBridge";
import logoUrl from "@/assets/taskorbit-logo.png";
import { TranscriptBubble } from "@/components/history/TranscriptBubble";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { useVoiceCall } from "@/hooks/useVoiceCall";
import {
  ManualTransferVoiceBridge,
  type ManualTransferVoiceSyncFn,
  WorkflowVoiceSyncBridge,
  type WorkflowVoiceSyncFn,
  type WorkflowVoiceState,
} from "@/hooks/useWorkflowVoiceSync";
import type { TranscriptionSegment } from "@/hooks/useAgentTranscription";
import { useActiveAgent } from "@/components/active-agent-provider";
import { buildLiveKitWorkerMetadata } from "@/lib/livekitAgentMetadata";
import { sendMessage, sendMessageStream, getConversations } from "@/lib/conversationApi";
import { playSynthesizedSpeech } from "@/lib/ttsApi";
import { backendToFrontendAgent, fetchUserAgents } from "@/lib/userAgentsApi";
import type { AgentConfig } from "@/types/agentConfig";
import type { LiveTranscriptTurn } from "@/types/callState";

/**
 * Returns ElevenLabs-specific TTS options only when the provider is elevenlabs.
 * The REST /v1/tts/synthesize endpoint is ElevenLabs-only — passing Deepgram
 * model names causes silent failures. Returns {} for all other providers so
 * the env-default ElevenLabs voice is used as fallback.
 * @param tts - the agent TTS config
 */
function restTtsOptions(tts: AgentConfig["tts"]): { voiceId?: string; modelId?: string } {
  if (tts.provider !== "elevenlabs") return {};
  return { voiceId: tts.voice_id, modelId: tts.model };
}

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

const BUILTIN_INTENT_AGENT_NAMES = new Set([
  "sales",
  "general_inquiry",
  "technical_support",
  "customer_dissatisfaction",
  "appointment_management",
  "general inquiry",
]);

function formatRoutedAgentBadgeLabel(
  routedAgent: string | null,
  entryAgentId: string,
): string | null {
  if (!routedAgent) return null;
  const normalised = routedAgent.replace(/_/g, " ").toLowerCase();
  if (BUILTIN_INTENT_AGENT_NAMES.has(normalised)) return null;
  if (routedAgent === entryAgentId) return null;
  return `${routedAgent.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())} Agent`;
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
  const routedAgentRef = useRef<string | null>(null);
  const completedWorkflowStepsRef = useRef<string[]>([]);
  const workflowVoiceSyncRef = useRef<WorkflowVoiceSyncFn | null>(null);
  useEffect(() => {
    routedAgentRef.current = routedAgent;
  }, [routedAgent]);
  useEffect(() => {
    completedWorkflowStepsRef.current = completedWorkflowSteps;
  }, [completedWorkflowSteps]);
  const registerWorkflowVoiceSync = useCallback((sync: WorkflowVoiceSyncFn | null) => {
    workflowVoiceSyncRef.current = sync;
  }, []);
  const manualTransferVoiceRef = useRef<ManualTransferVoiceSyncFn | null>(null);
  const registerManualTransferVoiceSync = useCallback(
    (sync: ManualTransferVoiceSyncFn | null) => {
      manualTransferVoiceRef.current = sync;
    },
    [],
  );
  const syncWorkflowToVoice = useCallback(async (state: WorkflowVoiceState) => {
    try {
      await workflowVoiceSyncRef.current?.(state);
    } catch (err) {
      console.warn("[ConversationalChat] workflow voice sync failed", err);
    }
  }, []);
  const [previousConversations, setPreviousConversations] = useState<RecentConversation[]>([]);
  const [recentLoading, setRecentLoading] = useState(true);
  const [recentError, setRecentError] = useState(false);
  // Last-write-wins guard: the mount load and the on-call-end refresh can be
  // in flight together, and on a slow network / cold start the older one may
  // resolve last and clobber the fresher list. Ignore any load that a newer
  // one has superseded.
  const recentReqIdRef = useRef(0);

  const loadConversations = useCallback(async () => {
    const reqId = ++recentReqIdRef.current;
    setRecentError(false);
    try {
      const data = await getConversations();
      if (reqId !== recentReqIdRef.current) return;
      setPreviousConversations(data.conversations || []);
    } catch {
      if (reqId !== recentReqIdRef.current) return;
      setRecentError(true);
    } finally {
      if (reqId === recentReqIdRef.current) setRecentLoading(false);
    }
  }, []);

  // Load on mount, then refresh whenever a call ends so the just-finished
  // conversation appears in the Recent panel without a manual reload.
  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (call.status === "ended") void loadConversations();
  }, [call.status, loadConversations]);

  // Agent segment merging: livekit-agents emits one stream per TTS chunk,
  // each with a unique lk.segment_id. We collapse them into a single turn
  // (agentTurnIdRef) so the bubble grows instead of spawning new bubbles.
  const agentTurnIdRef = useRef<string | null>(null);
  const agentCommittedRef = useRef<string>("");
  const agentActiveSegRef = useRef<string | null>(null);
  /** Set once the opening greeting is in the transcript; blocks late TTS re-streams. */
  const greetingEstablishedRef = useRef(false);

  const isGreetingReplay = useCallback(
    (text: string) => {
      const greeting = agent.first_message.message?.trim();
      if (!greeting || !greetingEstablishedRef.current) return false;
      const t = text.trim();
      if (!t) return false;
      return t.length < greeting.length && greeting.startsWith(t);
    },
    [agent.first_message.message],
  );

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
      greetingEstablishedRef.current = false;
    }
  }, [call.status]);

  // Lock out late greeting TTS transcription replays once the greeting is in the transcript.
  useEffect(() => {
    const greeting = agent.first_message.message?.trim();
    if (!greeting) return;
    if (call.transcript.some((t) => t.role === "assistant" && t.text.trim() === greeting)) {
      greetingEstablishedRef.current = true;
    }
  }, [call.transcript, agent.first_message.message]);

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
      if (segment.role === "assistant") {
        const greeting = agent.first_message.message?.trim();
        if (greeting) {
          const t = segment.text.trim();
          if (t === greeting) {
            greetingEstablishedRef.current = true;
          }
          if (isGreetingReplay(t)) {
            return;
          }
        }
      }

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
      const trimmed = mergedText.trim();
      if (!trimmed) return;

      if (segment.role === "assistant") {
        const greeting = agent.first_message.message?.trim();
        if (greeting && trimmed === greeting) {
          greetingEstablishedRef.current = true;
        }
        if (isGreetingReplay(trimmed)) {
          return;
        }
      }

      call.upsertTurnById(agentTurnIdRef.current, "assistant", trimmed, segment.isFinal);

      // Once this chunk is final, grow the committed base for the next chunk.
      if (segment.isFinal) {
        agentCommittedRef.current = trimmed;
      }
    },
    [call, agent.first_message.message, isGreetingReplay],
  );

  const handleSendText = useCallback(
    (
      text: string,
      manualTransfer?: { target_agent_id: string; target_agent_name: string } | null,
    ) => {
      // Voice calls are mic-driven; typing would run a second SSE+TTS path in parallel
      // with the LiveKit worker and duplicate greetings/audio.
      if (call.livekitCredentials !== null) {
        return;
      }

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
            completedWorkflowStepsRef.current,
            routedAgentRef.current,
            manualTransfer ?? null,
          );

          for await (const event of stream) {
            if (event.type === "chunk") {
              replyText += event.text;
              call.upsertTurnById(assistantTurnId, "assistant", replyText, false);
            } else if (event.type === "done") {
              const finalText = (replyText.trim() || event.reply?.trim() || "").trim();
              const isConfirmation =
                (event.status === "confirmation_required" ||
                  event.status === "workflow_confirmation_required") &&
                event.confirmation;

              if (event.conversation_id) call.updateConversationId(event.conversation_id);
              if (event.locked_intent_name) {
                lockedIntentRef.current = event.locked_intent_name;
              }
              setCompletedWorkflowSteps(event.completed_workflow_steps ?? []);

              if (!manualTransfer && event.selected_agent) {
                setRoutedAgent(event.selected_agent);
              }

              if (call.status !== "idle" && call.status !== "ended") {
                void syncWorkflowToVoice({
                  selected_agent: event.selected_agent ?? routedAgentRef.current,
                  completed_workflow_steps: event.completed_workflow_steps ?? [],
                  clear_pending_confirmation: !isConfirmation,
                });
              }

              if (isConfirmation) {
                // Proceed/Cancel card carries the prompt — no duplicate bubble in transcript.
                call.removeTurnById(assistantTurnId);
                pendingConfirmationIdRef.current = event.confirmation!.confirmation_id;
                call.triggerConfirmation({
                  ...event.confirmation!,
                  type: event.status === "workflow_confirmation_required" ? "workflow" : "tool",
                });
                call.setPhase("idle_in_call");
                return;
              }

              replyText = finalText;
              if (finalText) {
                call.upsertTurnById(assistantTurnId, "assistant", finalText, true);
              } else {
                call.removeTurnById(assistantTurnId);
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
                    ...restTtsOptions(agent.tts),
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
                    // The backend sends the canonical target: a registry name
                    // ("general_inquiry") for built-ins, or a row id for saved
                    // agents. Bridge kebab template ids the same way as
                    // useAgentHandoff so both paths match identically (#212).
                    const match = entries.find((e) => {
                      const uaId = e.template_id ?? e.id;
                      if (uaId === targetId || e.id === targetId) return true;
                      const normalized = uaId.replace(/-agent$/, "").replace(/-/g, "_");
                      return normalized === targetId;
                    });
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
              // Prefer the polite reply from #197 for the assistant bubble.
              // Fall back to the technical message only for legacy backend
              // paths that predate the reply-on-error contract.
              const politeReply = event.reply?.trim();
              const errorBubble = politeReply || `[Error: ${event.message}]`;
              call.upsertTurnById(assistantTurnId, "assistant", errorBubble, true);
              // Route the polite reply through TTS as well so voice users hear
              // it. `replyText` is what the speaker branch below reads.
              if (politeReply) {
                replyText = politeReply;
              }
            }
          }

          const speakable =
            replyText.trim().length > 0 &&
            !replyText.startsWith("[Connection error") &&
            call.livekitCredentials === null;
          if (speakable) {
            call.setPhase("speaking");
            try {
              await playSynthesizedSpeech(replyText, {
                signal: controller.signal,
                volumeRef: agentVolumeRef,
                ...restTtsOptions(agent.tts),
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
    [agent, call, syncWorkflowToVoice],
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
        // #212: a cleared pick must also clear the worker's pending transfer,
        // otherwise the next voice turn would still hard-transfer.
        if (call.livekitCredentials !== null) {
          manualTransferVoiceRef.current?.(null).catch((err) => {
            console.warn("[ConversationalChat] manual transfer clear failed", err);
          });
        }
        return;
      }
      const badgeName = target.name.replace(/\s+[Aa]gent$/i, "").trim();
      manualRoutingLockRef.current = true;
      setRoutedAgent(badgeName);
      const transferMsg = `Transferring you to ${target.name} upon your request.`;
      call.appendAssistantTurn(transferMsg);
      playSynthesizedSpeech(transferMsg, restTtsOptions(agent.tts)).catch(() => {});
      // #212: during a live voice call there is no typed message to carry
      // manual_transfer, so hand the pick to the worker over the data channel;
      // it applies the hard transfer on the next voice turn and publishes the
      // agent_handoff swap back to us.
      if (call.livekitCredentials !== null) {
        manualTransferVoiceRef.current?.({
          target_agent_id: target.id,
          target_agent_name: target.name,
        }).catch((err) => {
          console.warn("[ConversationalChat] manual transfer publish failed", err);
        });
      }
    },
    [call, agent.tts],
  );

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
            completedWorkflowStepsRef.current,
            routedAgentRef.current,
          );
          call.updateConversationId(response.conversation_id);
          if (response.locked_intent_name) {
            lockedIntentRef.current = response.locked_intent_name;
          }
          setCompletedWorkflowSteps(response.completed_workflow_steps ?? []);

          if (response.selected_agent) {
            setRoutedAgent(response.selected_agent);
          }

          if (confirmationId.startsWith("workflow_")) {
            await syncWorkflowToVoice({
              selected_agent: response.selected_agent,
              completed_workflow_steps: response.completed_workflow_steps ?? [],
              clear_pending_confirmation: true,
            });
          } else if (call.status !== "idle" && call.status !== "ended") {
            await syncWorkflowToVoice({
              selected_agent: response.selected_agent ?? routedAgentRef.current,
              completed_workflow_steps: response.completed_workflow_steps ?? [],
              clear_pending_confirmation: true,
            });
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
            replyText.trim().length > 0 &&
            !replyText.startsWith("[Connection error") &&
            call.livekitCredentials === null;
          if (speakable) {
            call.setPhase("speaking");
            try {
              await playSynthesizedSpeech(replyText, {
                signal: controller.signal,
                volumeRef: agentVolumeRef,
                ...restTtsOptions(agent.tts),
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
    [agent, call, syncWorkflowToVoice],
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
    greetingEstablishedRef.current = false;
    setRoutedAgent(null);
    setCompletedWorkflowSteps([]);
    call.restart();
  }, [call]);

  const handleStartSession = useCallback(() => {
    lockedIntentRef.current = null;
    pendingConfirmationIdRef.current = null;
    greetingEstablishedRef.current = false;
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
  const routedAgentBadgeLabel = useMemo(
    () => formatRoutedAgentBadgeLabel(routedAgent, agent.agent_id),
    [routedAgent, agent.agent_id],
  );

  const body: ReactNode = (
    <div
      className={cn(
        "mx-auto flex min-h-svh flex-col gap-6 px-4 py-8 sm:px-6 sm:py-10",
        isPreCall ? "max-w-6xl" : "max-w-5xl",
      )}
    >
      <header className="space-y-1">
        <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
          Conversational agent
        </p>
        <div className="flex items-center gap-3">
          <img src={logoUrl} alt="" className="size-9 shrink-0" />
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{appName}</h1>
        </div>
        <p className="text-sm text-muted-foreground">
          Start a session to talk with your agent by voice, or use the text option.
        </p>
      </header>

      {isPreCall ? (
        <div className="grid animate-in gap-6 fade-in slide-in-from-bottom-2 duration-500 ease-out lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="flex flex-col gap-6">
            <AgentIdentityCard agent={agent} />
            <CallControls
              status="idle"
              onStart={handleStartSession}
              onSendText={handleSendText}
              onRestart={handleRestart}
            />
            <AgentSwitcher
              activeAgentId={agent.agent_id}
              activeAgentName={agent.name}
              onSelect={(entry) =>
                setActiveAgent(backendToFrontendAgent(entry), `ua:${entry.template_id ?? entry.id}`)
              }
            />
          </div>
          <div className="flex flex-col gap-6">
            <RecentConversations
              conversations={previousConversations}
              isLoading={recentLoading}
              error={recentError}
            />
            <PreCallDiagnostics />
          </div>
        </div>
      ) : null}

      {isInCall ? (
        <Card
          className={cn(
            "transition-all duration-500 ease-out",
            call.status === "ending" && "scale-[0.98] opacity-50",
          )}
        >
          <CardHeader className="flex flex-row items-start justify-between gap-3 border-b">
            <div className="space-y-1">
              <CardTitle>{agent.name}</CardTitle>
              <CardDescription>
                {call.status === "connecting"
                  ? "Connecting to your agent…"
                  : call.status === "ending"
                    ? "Ending call…"
                    : "Voice session active · live transcript below."}
              </CardDescription>
            </div>
            <div className="flex flex-col items-end gap-2">
              <CallStatusIndicator status={call.status} />
              {routedAgentBadgeLabel && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
                  <span className="size-1.5 rounded-full bg-primary" />
                  {routedAgentBadgeLabel}
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
        <Card className="animate-in fade-in slide-in-from-bottom-2 duration-500 ease-out">
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
            disableTextInput
            onPhase={call.setPhase}
            onEnd={call.end}
            onSendText={handleSendText}
            onRoutingTargetChange={handleRoutingTargetChange}
            onMicError={call.setMicError}
            agentMuted={agentMuted}
            onAgentMutedChange={setAgentMuted}
          />
        </div>
      ) : isInCall ? null : isPostCall ? (
        <CallControls
          status={call.status}
          onStart={handleStartSession}
          onSendText={handleSendText}
          onRestart={handleRestart}
        />
      ) : null}
    </div>
  );

  return (
    <div>
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
            onConnectionLost={call.reportConnectionLost}
          />
          <WorkflowVoiceSyncBridge onRegister={registerWorkflowVoiceSync} />
          <ManualTransferVoiceBridge onRegister={registerManualTransferVoiceSync} />
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
    </div>
  );
}
