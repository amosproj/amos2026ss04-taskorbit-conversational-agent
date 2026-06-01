import { LiveKitRoom, RoomAudioRenderer } from "@livekit/components-react";
import { useCallback, useEffect, useRef, useState } from "react";
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
import { sendMessage, getConversations } from "@/lib/conversationApi";
import { playSynthesizedSpeech } from "@/lib/ttsApi";
import { backendToFrontendAgent, fetchUserAgents } from "@/lib/userAgentsApi";
import type { ConfirmationPromptState } from "@/types/callState";

const mockConfirmationPrompt: ConfirmationPromptState = {
  id: "demo-confirmation",
  tool_name: "collect_user_info",
  prompt: "I'll save the details we just discussed to your account. Is that okay?",
};

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
  const greetingSeenSpeakingRef = useRef(false);
  const greetingTimeoutRef = useRef<number | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const lastUserTurnIdRef = useRef<string | null>(null);
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
    (text: string) => {
      call.appendUserTurn(text);
      call.setPhase("thinking");

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      void Promise.resolve().then(async () => {
        try {
          const response = await sendMessage(
            agent,
            [{ id: "tmp", role: "user", text }],
            call.conversationId,
            controller.signal,
          );
          const replyText = response.reply.content;
          call.appendAssistantTurn(replyText);

          // Agent handoff (#8 Task 6): backend's IntentRouter / dispatch decided
          // to transfer the conversation. Swap the displayed agent and add a
          // transcript marker so the user sees the switch.
          // NOTE: backend currently exposes only the agent's configured targets
          // in tool_invoked.parameters; the actual transferred_to id from
          // ToolResult.data is not propagated (orchestration/__init__.py:169).
          // First target works for single-target configs (e.g. JOHN_DOE_AGENT).
          if (response.tool_invoked?.type === "agent_transfer") {
            const targets = (response.tool_invoked.parameters as { targets?: string[] })?.targets;
            const targetId = targets?.[0];
            if (targetId) {
              try {
                const entries = await fetchUserAgents(controller.signal);
                const match = entries.find((e) => e.template_id === targetId || e.id === targetId);
                if (match) {
                  const next = backendToFrontendAgent(match);
                  setActiveAgent(next, `ua:${match.template_id ?? match.id}`);
                  call.appendAssistantTurn(`[Transferred to ${next.name}]`);
                }
              } catch (transferErr) {
                if ((transferErr as Error).name !== "AbortError") {
                  console.warn("[ConversationalChat] agent transfer lookup failed", transferErr);
                }
              }
            }
          }

          const speakable =
            replyText.trim().length > 0 && !replyText.startsWith("[Connection error");
          if (speakable) {
            call.setPhase("speaking");
            try {
              await playSynthesizedSpeech(replyText, { signal: controller.signal });
            } catch (audioErr) {
              if ((audioErr as Error).name !== "AbortError") {
                console.warn("[ConversationalChat] ElevenLabs playback failed", audioErr);
              }
            }
          }
          call.setPhase("idle_in_call");
        } catch (err) {
          if ((err as Error).name === "AbortError") return;
          call.appendAssistantTurn(`[Connection error: ${(err as Error).message}]`);
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

  const handleTriggerConfirmation = useCallback(() => {
    call.triggerConfirmation(mockConfirmationPrompt);
  }, [call]);

  const handleApprove = useCallback(() => {
    const followup = "Thanks for confirming — I've saved that. Anything else?";
    call.approveConfirmation(followup);
    void playSynthesizedSpeech(followup).catch(() => {
      /* optional TTS */
    });
  }, [call]);

  const handleDeny = useCallback(() => {
    const followup = "Understood — I won't save that. Anything else?";
    call.denyConfirmation(followup);
    void playSynthesizedSpeech(followup).catch(() => {
      /* optional TTS */
    });
  }, [call]);

  const handleStartSession = useCallback(() => {
    // console.log("[greeting] handleStartSession fired");
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
            <CallStatusIndicator status={call.status} />
          </CardHeader>
          <CardContent className="pt-6">
            <ScrollArea className="h-[min(50vh,28rem)] pr-3">
              {call.status === "connecting" ? (
                <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                  Waiting for agent to join…
                </div>
              ) : (
                <ul className="flex flex-col gap-4" aria-label="Transcript">
                  {call.transcript.map((turn) => (
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
              {call.transcript.length > 0
                ? `${call.transcript.length} turn${call.transcript.length === 1 ? "" : "s"} recorded.`
                : "No turns recorded."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[min(40vh,24rem)] pr-3">
              <ul className="flex flex-col gap-4" aria-label="Transcript">
                {call.transcript.map((turn) => (
                  <TranscriptBubble key={turn.id} turn={turn} history />
                ))}
              </ul>
            </ScrollArea>
          </CardContent>
        </Card>
      ) : null}

      {call.confirmation !== null ? (
        <ConfirmationPrompt
          prompt={call.confirmation}
          onApprove={handleApprove}
          onDeny={handleDeny}
        />
      ) : isInCall ? (
        call.livekitCredentials !== null ? (
          <InCallControls
            status={call.status}
            greetingInProgress={!greetingDone}
            onPhase={call.setPhase}
            onEnd={call.end}
            onSendText={handleSendText}
            onTriggerConfirmation={handleTriggerConfirmation}
            onMicError={call.setMicError}
          />
        ) : null
      ) : (
        <CallControls
          status={call.status}
          onStart={handleStartSession}
          onSendText={handleSendText}
          onRestart={call.restart}
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
          <RoomAudioRenderer />
          <VoiceSessionBridge
            status={call.status}
            onPhase={call.setPhase}
            onSegment={handleSegment}
            onHandoff={handleVoiceHandoff}
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
    </main>
  );
}
