import { LiveKitRoom, RoomAudioRenderer } from "@livekit/components-react";
import { useCallback, useEffect, useRef } from "react";
import type { ReactNode } from "react";

import { AgentIdentityCard } from "@/components/chat/AgentIdentityCard";
import { CallControls } from "@/components/chat/CallControls";
import { CallStatusIndicator } from "@/components/chat/CallStatusIndicator";
import { ConfirmationPrompt } from "@/components/chat/ConfirmationPrompt";
import { InCallControls } from "@/components/chat/InCallControls";
import { PreCallDiagnostics } from "@/components/chat/PreCallDiagnostics";
import { VoiceSessionBridge } from "@/components/chat/VoiceSessionBridge";
import { TranscriptBubble } from "@/components/history/TranscriptBubble";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useVoiceCall } from "@/hooks/useVoiceCall";
import type { TranscriptionSegment } from "@/hooks/useAgentTranscription";
import { buildLiveKitWorkerMetadata } from "@/lib/livekitAgentMetadata";
import { sendMessage } from "@/lib/conversationApi";
import { JOHN_DOE_AGENT } from "@/lib/mockAgents";
import { playSynthesizedSpeech } from "@/lib/ttsApi";
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
  const agent = JOHN_DOE_AGENT;
  const appName = import.meta.env.VITE_APP_NAME ?? "TaskOrbit";

  const call = useVoiceCall();
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const lastUserTurnIdRef = useRef<string | null>(null);

  // Keep transcript rendering anchored to the latest turn.
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [call.transcript]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleSegment = useCallback(
    (segment: TranscriptionSegment) => {
      if (segment.role === "user") {
        lastUserTurnIdRef.current = segment.id;
        call.upsertTurnById(segment.id, "user", segment.text);
        return;
      }

      // livekit-agents plays this when llm_node returns empty (no reply).
      // Remove the user turn that triggered it — it was never processed.
      if (
        segment.isFinal &&
        segment.text.toLowerCase().includes("i didn't get your message")
      ) {
        if (lastUserTurnIdRef.current) {
          call.removeTurnById(lastUserTurnIdRef.current);
          lastUserTurnIdRef.current = null;
        }
      }

      call.upsertTurnById(segment.id, "assistant", segment.text);
    },
    [call],
  );

  // Text fallback path — keeps the typed input working when the user
  // can't or doesn't want to speak. Uses the legacy /v1/conversations
  // endpoint which round-trips through the orchestrator stub. The voice
  // path streams its own transcript via VoiceSessionBridge.
  const handleSendText = useCallback(
    (text: string) => {
      call.appendUserTurn(text);
      call.setPhase("thinking");

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      void Promise.resolve().then(async () => {
        try {
          const reply = await sendMessage(
            agent,
            [{ id: "tmp", role: "user", text }],
            call.conversationId,
            controller.signal,
          );
          call.appendAssistantTurn(reply);
          const speakable =
            reply.trim().length > 0 &&
            !reply.startsWith("[Connection error");
          if (speakable) {
            call.setPhase("speaking");
            try {
              await playSynthesizedSpeech(reply, {
                signal: controller.signal,
                voiceId: agent.tts.voice_id,
                modelId: agent.tts.model,
              });
            } catch (audioErr) {
              if ((audioErr as Error).name !== "AbortError") {
                // eslint-disable-next-line no-console
                console.warn("[ConversationalChat] ElevenLabs playback failed", audioErr);
              }
            }
          }
          call.setPhase("idle_in_call");
        } catch (err) {
          if ((err as Error).name === "AbortError") return;
          call.appendAssistantTurn(
            `[Connection error: ${(err as Error).message}]`,
          );
          call.setPhase("idle_in_call");
        }
      });
    },
    [agent, call],
  );

  const handleTriggerConfirmation = useCallback(() => {
    call.triggerConfirmation(mockConfirmationPrompt);
  }, [call]);

  const handleApprove = useCallback(() => {
    const followup =
      "Thanks for confirming — I've saved that. Anything else?";
    call.approveConfirmation(followup);
    void playSynthesizedSpeech(followup, {
      voiceId: agent.tts.voice_id,
      modelId: agent.tts.model,
    }).catch(() => {
      /* optional TTS */
    });
  }, [agent.tts, call]);

  const handleDeny = useCallback(() => {
    const followup = "Understood — I won't save that. Anything else?";
    call.denyConfirmation(followup);
    void playSynthesizedSpeech(followup, {
      voiceId: agent.tts.voice_id,
      modelId: agent.tts.model,
    }).catch(() => {
      /* optional TTS */
    });
  }, [agent.tts, call]);

  const handleStartSession = useCallback(() => {
    call.start({
      tokenMetadata: buildLiveKitWorkerMetadata(agent),
      greeting: agent.first_message.message,
    });
    if (agent.first_message.message) {
      void playSynthesizedSpeech(agent.first_message.message, {
        voiceId: agent.tts.voice_id,
        modelId: agent.tts.model,
      }).catch(() => {
        /* optional TTS */
      });
    }
  }, [agent, call]);

  const isPreCall = call.status === "idle";
  const isPostCall = call.status === "ended";
  const isInCall = !isPreCall && !isPostCall;

  // The page body. We render it directly while idle/ended, and wrap it
  // in `<LiveKitRoom>` once we have credentials so that hooks inside
  // (mic recorder, transcription) get the room context.
  const body: ReactNode = (
    <div className="mx-auto flex min-h-svh max-w-2xl flex-col gap-6 px-4 py-8 sm:px-6 sm:py-10">
      <header className="space-y-1">
        <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
          Conversational agent
        </p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          {appName}
        </h1>
        <p className="text-sm text-muted-foreground">
          Start a voice session with the configured agent. Tap the mic
          to speak, then Send your turn for a reply.
        </p>
      </header>

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
                Live call · transcript updates as the conversation
                progresses.
              </CardDescription>
            </div>
            <CallStatusIndicator status={call.status} agentName={agent.name} />
          </CardHeader>
          <CardContent className="pt-6">
            <ScrollArea className="h-[min(50vh,28rem)] pr-3">
              <ul className="flex flex-col gap-4" aria-label="Transcript">
                {call.transcript.map((turn) => (
                  <TranscriptBubble key={turn.id} turn={turn} />
                ))}
                <div ref={transcriptEndRef} className="h-px" aria-hidden />
              </ul>
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
                  <TranscriptBubble key={turn.id} turn={turn} />
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
        // InCallControls reads `useLocalParticipant` and must live
        // inside LiveKitRoom — only render when credentials are
        // available so the hook can find the room context.
        call.livekitCredentials !== null ? (
          <InCallControls
            status={call.status}
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
          onError={(err) => {
            if (
              err.name === "NotAllowedError" ||
              err.message.includes("Permission")
            ) {
              call.setMicError(
                "Microphone access was denied. Please allow microphone access to use voice.",
              );
            }
          }}
        >
          <RoomAudioRenderer />
          <VoiceSessionBridge
            status={call.status}
            onPhase={call.setPhase}
            onSegment={handleSegment}
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
