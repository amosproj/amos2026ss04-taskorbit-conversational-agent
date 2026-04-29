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
import { JOHN_DOE_AGENT } from "@/lib/mockAgents";
import type {
  CallStatus,
  ConfirmationPromptState,
  LiveTranscriptTurn,
} from "@/types/callState";

const CONNECTING_DELAY_MS = 800;
const THINKING_DELAY_MS = 1200;
const SPEAKING_DELAY_MS = 2600;

function generateId(prefix: string): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function mockAgentReply(userText: string): string {
  const trimmed = userText.trim().toLowerCase();
  if (!trimmed) return "Could you repeat that?";
  if (trimmed.includes("hello") || trimmed.includes("hi")) {
    return "Hi! How can I help you today?";
  }
  if (trimmed.includes("name")) {
    return "Got it. Anything else you'd like to share?";
  }
  if (trimmed.includes("bye")) {
    return "Thanks for calling — goodbye!";
  }
  return `I heard "${userText.trim()}". This is a mock reply — the real LLM lands in Sprint 3 (#18).`;
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

  const timerRef = useRef<number | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  // Mirror status in a ref so async timers can read the latest phase
  // without going stale across rapid transitions.
  const statusRef = useRef<CallStatus>(status);
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  // Auto-scroll transcript to the latest turn.
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  // Cancel any pending timer on unmount so we don't fire setState on an
  // unmounted component during teardown.
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
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

  // After a user turn, run thinking → speaking → back to listening. The
  // confirmation flow is reachable only via the "Demo confirmation"
  // button so the harness stays operator-driven and doesn't assert
  // behaviour the agent's `confirmations` block hasn't enabled.
  const runAgentResponseCycle = useCallback(
    (userText: string) => {
      clearTimer();
      setStatus("thinking");
      timerRef.current = window.setTimeout(() => {
        if (statusRef.current !== "thinking") return;
        const reply = mockAgentReply(userText);
        appendAssistantTurn(reply);
        setStatus("speaking");
        timerRef.current = window.setTimeout(() => {
          if (statusRef.current !== "speaking") return;
          setStatus("listening");
        }, SPEAKING_DELAY_MS);
      }, THINKING_DELAY_MS);
    },
    [appendAssistantTurn, clearTimer],
  );

  const handleStart = useCallback(() => {
    clearTimer();
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
    setConfirmation(null);
    setStatus("ended");
  }, [clearTimer]);

  const handleRestart = useCallback(() => {
    clearTimer();
    setTranscript([]);
    setConfirmation(null);
    setStatus("idle");
  }, [clearTimer]);

  const handleSendText = useCallback(
    (text: string) => {
      if (status !== "listening") return;
      appendUserTurn(text);
      runAgentResponseCycle(text);
    },
    [appendUserTurn, runAgentResponseCycle, status],
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
