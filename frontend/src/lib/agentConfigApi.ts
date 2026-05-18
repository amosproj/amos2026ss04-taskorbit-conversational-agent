/**
 * Thin client for the /api/v1/agent-configs endpoints.
 *
 * Persists the full FE-side AgentConfig (Preet's reference shape) so the
 * user can come back later and reuse a preset. The backend stores the
 * config as opaque JSON via `AgentConfigurationDetail.config: dict[str, Any]`,
 * so the round-trip preserves every FE field — no adapter needed here.
 * The Vite dev server proxies `/api/*` to the backend (see
 * `frontend/vite.config.ts`), so this works without CORS configuration
 * in development.
 *
 * Implements ticket #47 (Save Agent Configuration). Load + update + delete
 * are owned by the sibling tickets #51 and #52 on the same feature branch.
 */

import { serializeAgent, type AgentConfig } from "@/types/agentConfig";

export type SavedAgentConfig = {
  id: string;
  name: string;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string | null;
};

/**
 * Persist an agent configuration to the backend.
 *
 * Uses the existing `agent.name` field as the save identifier — consistent
 * with the meeting decision to scope this ticket tight (no separate
 * "save as…" modal).
 *
 * @param agent  - The full AgentConfig the user has been editing
 * @param signal - Optional AbortSignal to cancel the in-flight request
 * @returns The saved row, including the DB-assigned id and timestamps
 * @throws Error with the backend's `detail` message when the response is non-2xx.
 */
export async function saveAgentConfig(
  agent: AgentConfig,
  signal?: AbortSignal,
): Promise<SavedAgentConfig> {
  const res = await fetch("/api/v1/agent-configs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: agent.name,
      config: serializeAgent(agent),
    }),
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }

  return (await res.json()) as SavedAgentConfig;
}
