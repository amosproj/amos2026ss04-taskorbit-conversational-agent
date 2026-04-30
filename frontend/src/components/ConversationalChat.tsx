import { useCallback, useEffect, useRef, useState } from "react";

import { AgentIdentityCard } from "@/components/chat/AgentIdentityCard";
import { CallControls } from "@/components/chat/CallControls";
import { CallStatusIndicator } from "@/components/chat/CallStatusIndicator";
import { ConfirmationPrompt } from "@/components/chat/ConfirmationPrompt";
import { PreCallDiagnostics } from "@/components/chat/PreCallDiagnostics";
import { TranscriptBubble } from "@/components/history/TranscriptBubble";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { sendMessage } from "@/lib/conversationApi";
import { JOHN_DOE_AGENT } from "@/lib/mockAgents";
import type {
  CallStatus,
  ConfirmationPromptState,
  LiveTranscriptTurn,
} from "@/types/callState";

const CONNECTING_DELAY_MS = 800;
const SPEAKING_DELAY_MS = 2600;

function generateId(prefix: string): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function generateConversationId(): string {
  return `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const mockConfirmationPrompt: ConfirmationPromptState = {
  id: "demo-confirmation",
  tool_name: "collect_user_info",
  prompt: "I'll save the details we just discussed to your account. Is that okay?",
};

/**
 * Live call surface for the Meisterwerk-customer end of the agent
 * pipeline. Models the call as an explicit state machine — `idle`,
 * `connecting`, `listening`, `thinking`, `speaking`,
 * `awaiting_confirmation`, `ended` — so each phase has a single source
 * of truth for the UI shape. Sprint 2 mocks the transitions with timers;
 * Sprint 3 (#14, #15, #26) will drive the same states from LiveKit room
 * events without restructuring this component.
 */
export function ConversationalChat() {
  const agent = JOHN_DOE_AGENT;
  const appName = import.meta.env.VITE_APP_NAME ?? "TaskOrbit";

  const [status, setStatus] = useState<CallStatus>("idle");
  const [transcript, setTranscript] = useState<LiveTranscriptTurn[]>([]);
  const [confirmation, setConfirmation] =
    useState<ConfirmationPromptState | null>(null);
  const [conversationId, setConversationId] = useState<string>("");

  const timerRef = useRef<number | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  // Mirror status in a ref so async callbacks can read the latest phase
  // without going stale across rapid transitions.
  const statusRef = useRef<CallStatus>(status);
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  // Mirror transcript in a ref so the async sendMessage call always
  // sees the latest turns (including the user turn just appended).
  const transcriptRef = useRef<LiveTranscriptTurn[]>(transcript);
  useEffect(() => {
    transcriptRef.current = transcript;
  }, [transcript]);

  // AbortController for the in-flight backend request — cancelled when
  // the user ends the call or starts a new one.
  const abortRef = useRef<AbortController | null>(null);

  // Auto-scroll transcript to the latest turn.
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  // Cancel pending timers and in-flight requests on unmount.
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      abortRef.current?.abort();
    };
  }, []);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const appendAssistantTurn = useCallback((text: string) => {
    setTranscript((t) => [
      ...t,
      { id: generateId("a"), role: "assistant", text },
    ]);
  }, []);

  const appendUserTurn = useCallback((text: string) => {
    setTranscript((t) => [...t, { id: generateId("u"), role: "user", text }]);
  }, []);

  // After a user turn is appended to transcript, call the backend and
  // run the thinking → speaking → listening transition. The thinking phase
  // lasts until the backend responds (real latency replaces the old timer).
  const runAgentResponseCycle = useCallback(
    (convId: string) => {
      clearTimer();
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setStatus("thinking");

      // Use a microtask so React has flushed the latest transcript into
      // transcriptRef before we read it for the API call.
      void Promise.resolve().then(async () => {
        try {
          const reply = await sendMessage(
            agent,
            transcriptRef.current,
            convId,
            controller.signal,
          );
          if (statusRef.current !== "thinking") return;
          appendAssistantTurn(reply);
          setStatus("speaking");
          timerRef.current = window.setTimeout(() => {
            if (statusRef.current !== "speaking") return;
            setStatus("listening");
          }, SPEAKING_DELAY_MS);
        } catch (err) {
          if ((err as Error).name === "AbortError") return;
          if (statusRef.current !== "thinking") return;
          appendAssistantTurn(
            `[Connection error: ${(err as Error).message}]`,
          );
          setStatus("listening");
        }
      });
    },
    [agent, appendAssistantTurn, clearTimer],
  );

  const handleStart = useCallback(() => {
    clearTimer();
    abortRef.current?.abort();
    const newConvId = generateConversationId();
    setConversationId(newConvId);
    setTranscript([]);
    setConfirmation(null);
    setStatus("connecting");
    timerRef.current = window.setTimeout(() => {
      if (statusRef.current !== "connecting") return;
      appendAssistantTurn(agent.first_message.message);
      setStatus("listening");
    }, CONNECTING_DELAY_MS);
  }, [agent.first_message.message, appendAssistantTurn, clearTimer]);

  const handleEnd = useCallback(() => {
    clearTimer();
    abortRef.current?.abort();
    setConfirmation(null);
    setStatus("ended");
  }, [clearTimer]);

  const handleRestart = useCallback(() => {
    clearTimer();
    abortRef.current?.abort();
    setTranscript([]);
    setConversationId("");
    setConfirmation(null);
    setStatus("idle");
  }, [clearTimer]);

  const handleSendText = useCallback(
    (text: string) => {
      if (status !== "listening") return;
      appendUserTurn(text);
      runAgentResponseCycle(conversationId);
    },
    [appendUserTurn, conversationId, runAgentResponseCycle, status],
  );

  const handleTriggerConfirmation = useCallback(() => {
    if (
      status !== "listening" &&
      status !== "thinking" &&
      status !== "speaking"
    ) {
      return;
    }
    clearTimer();
    setConfirmation(mockConfirmationPrompt);
    setStatus("awaiting_confirmation");
  }, [clearTimer, status]);

  const handleApprove = useCallback(() => {
    setConfirmation(null);
    appendAssistantTurn(
      "Thanks for confirming — I've saved that. Anything else?",
    );
    setStatus("speaking");
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      if (statusRef.current !== "speaking") return;
      setStatus("listening");
    }, SPEAKING_DELAY_MS);
  }, [appendAssistantTurn, clearTimer]);

  const handleDeny = useCallback(() => {
    setConfirmation(null);
    appendAssistantTurn("Understood — I won't save that. Anything else?");
    setStatus("speaking");
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      if (statusRef.current !== "speaking") return;
      setStatus("listening");
    }, SPEAKING_DELAY_MS);
  }, [appendAssistantTurn, clearTimer]);

  const isPreCall = status === "idle";
  const isPostCall = status === "ended";
  const isInCall = !isPreCall && !isPostCall;

  return (
    <main className="min-h-svh bg-background text-foreground">
      <div className="mx-auto flex min-h-svh max-w-2xl flex-col gap-6 px-4 py-8 sm:px-6 sm:py-10">
        <header className="space-y-1">
          <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
            Conversational agent
          </p>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            {appName}
          </h1>
          <p className="text-sm text-muted-foreground">
            Start a voice session with the configured agent. Voice lands
            in Sprint 3 — for now, the call surface is mocked end-to-end
            so the flow can be reviewed.
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
              <CallStatusIndicator status={status} agentName={agent.name} />
            </CardHeader>
            <CardContent className="pt-6">
              <ScrollArea className="h-[min(50vh,28rem)] pr-3">
                <ul className="flex flex-col gap-4" aria-label="Transcript">
                  {transcript.map((turn) => (
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
                {transcript.length > 0
                  ? `${transcript.length} turn${transcript.length === 1 ? "" : "s"} recorded.`
                  : "No turns recorded."}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-[min(40vh,24rem)] pr-3">
                <ul className="flex flex-col gap-4" aria-label="Transcript">
                  {transcript.map((turn) => (
                    <TranscriptBubble key={turn.id} turn={turn} />
                  ))}
                </ul>
              </ScrollArea>
            </CardContent>
          </Card>
        ) : null}

        {confirmation !== null ? (
          <ConfirmationPrompt
            prompt={confirmation}
            onApprove={handleApprove}
            onDeny={handleDeny}
          />
        ) : (
          <CallControls
            status={status}
            onStart={handleStart}
            onEnd={handleEnd}
            onSendText={handleSendText}
            onTriggerConfirmation={handleTriggerConfirmation}
            onRestart={handleRestart}
          />
        )}
      </div>
    </main>
  );
}
