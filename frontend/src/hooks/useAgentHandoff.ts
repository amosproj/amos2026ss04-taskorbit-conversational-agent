/**
 * Subscribes to `taskorbit.agent_handoff` data-channel packets from the
 * voice worker and swaps the active agent in-place.
 *
 * The worker publishes a packet of shape `{type: "agent_handoff",
 * target: "<template-id>"}` after the orchestrator dispatches an
 * `agent_transfer` tool during a voice call. Without this hook the
 * voice path stays on the original agent visually, even though the
 * server-side conversation has already routed away.
 *
 * Mirrors the data-flow used by useAgentTranscription — same room
 * context, same topic-namespaced subscription — so the LiveKit room
 * stays open through the swap (AC7 of #8).
 *
 * Must be used inside a `<LiveKitRoom>`.
 */

import { useRoomContext } from "@livekit/components-react";
import { RoomEvent, type RemoteParticipant } from "livekit-client";
import { useEffect } from "react";

import { useActiveAgent } from "@/components/active-agent-provider";
import { backendToFrontendAgent, fetchUserAgents } from "@/lib/userAgentsApi";

const HANDOFF_TOPIC = "taskorbit.agent_handoff";

type HandoffPayload = {
  type: "agent_handoff";
  target: string;
};

function isHandoffPayload(value: unknown): value is HandoffPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { type?: unknown }).type === "agent_handoff" &&
    typeof (value as { target?: unknown }).target === "string"
  );
}

export function useAgentHandoff(onTransferred?: (agentName: string) => void): void {
  const room = useRoomContext();
  const { setActiveAgent } = useActiveAgent();

  useEffect(() => {
    if (!room) return;

    const handler = async (
      payload: Uint8Array,
      _participant?: RemoteParticipant,
      _kind?: unknown,
      topic?: string,
    ): Promise<void> => {
      if (topic !== HANDOFF_TOPIC) return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(new TextDecoder().decode(payload));
      } catch {
        return;
      }
      if (!isHandoffPayload(parsed)) return;

      try {
        const entries = await fetchUserAgents();
        // Fuzzy match: the backend normalizes "sales-agent" to "sales" (removes -agent, replaces - with _).
        // We check for exact matches first, then normalized matches to bridge this gap.
        const match = entries.find((e) => {
          // Customised agents publish their row UUID as the target (#212);
          // template_id would mask it, so check the row id explicitly, the
          // same way the text-path matcher does.
          if (e.id === parsed.target) return true;
          const uaId = e.template_id ?? e.id;
          if (uaId === parsed.target) return true;

          const normalizedUaId = uaId.replace(/-agent$/, "").replace(/-/g, "_");
          return normalizedUaId === parsed.target;
        });

        if (!match) {
          console.warn("[useAgentHandoff] no user-agent match for", parsed.target);
          return;
        }
        const next = backendToFrontendAgent(match);
        setActiveAgent(next, `ua:${match.template_id ?? match.id}`);
        onTransferred?.(next.name);
      } catch (err) {
        console.warn("[useAgentHandoff] swap failed", err);
      }
    };

    room.on(RoomEvent.DataReceived, handler);
    return () => {
      room.off(RoomEvent.DataReceived, handler);
    };
  }, [room, setActiveAgent, onTransferred]);
}
