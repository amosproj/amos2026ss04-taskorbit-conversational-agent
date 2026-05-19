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
 * Implements the save (#47) and load (#51) sides of the agent-config trio.
 * Update + delete (PUT/DELETE) are owned by the sibling ticket #52 on the
 * same feature branch.
 */

import { serializeAgent, type AgentConfig } from "@/types/agentConfig";

export type SavedAgentConfig = {
  id: string;
  name: string;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string | null;
};

/** Shape returned by `GET /api/v1/agent-configs` — omits the heavy `config` blob. */
export type SavedAgentConfigSummary = {
  id: string;
  name: string;
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

/**
 * Fetch the list of saved agent configurations (most recent first).
 *
 * Used to populate the "Load preset" dropdown on the Agent Configuration
 * page so the user can pick a previously saved preset and have its form
 * fields re-populated.
 *
 * @param signal - Optional AbortSignal to cancel the in-flight request
 * @returns Array of summaries (id + name + timestamps, no config blob)
 * @throws Error with the backend's `detail` message when the response is non-2xx.
 */
export async function listAgentConfigs(signal?: AbortSignal): Promise<SavedAgentConfigSummary[]> {
  const res = await fetch("/api/v1/agent-configs", { signal });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }

  return (await res.json()) as SavedAgentConfigSummary[];
}

/**
 * Fetch a single saved agent configuration by id.
 *
 * The returned `config` is the full FE contract that was saved, so it can
 * be fed straight into `setAgent(...)` on the page to re-populate every
 * section.
 *
 * @param configId - The DB id from a previous save / list response
 * @param signal   - Optional AbortSignal to cancel the in-flight request
 * @returns The saved row including the full `config` JSON
 * @throws Error with the backend's `detail` message when the response is non-2xx.
 */
export async function loadAgentConfig(
  configId: string,
  signal?: AbortSignal,
): Promise<SavedAgentConfig> {
  const res = await fetch(`/api/v1/agent-configs/${encodeURIComponent(configId)}`, { signal });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }

  return (await res.json()) as SavedAgentConfig;
}

/**
 * Update an existing agent configuration in the backend.
 *
 * @param configId - The DB id of the configuration to update
 * @param agent    - The updated AgentConfig
 * @param signal   - Optional AbortSignal to cancel the in-flight request
 * @returns The updated row
 * @throws Error with the backend's `detail` message when the response is non-2xx.
 */
export async function updateAgentConfig(
  configId: string,
  agent: AgentConfig,
  signal?: AbortSignal,
): Promise<SavedAgentConfig> {
  const res = await fetch(`/api/v1/agent-configs/${encodeURIComponent(configId)}`, {
    method: "PUT",
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

/**
 * Delete a saved agent configuration from the backend.
 *
 * @param configId - The DB id of the configuration to delete
 * @param signal   - Optional AbortSignal to cancel the in-flight request
 * @throws Error with the backend's `detail` message when the response is non-2xx.
 */
export async function deleteAgentConfig(configId: string, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`/api/v1/agent-configs/${encodeURIComponent(configId)}`, {
    method: "DELETE",
    signal,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }
}
