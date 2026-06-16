import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { JOHN_DOE_AGENT } from "@/lib/mockAgents";
import { backendToFrontendAgent, fetchUserAgents } from "@/lib/userAgentsApi";
import type { AgentConfig } from "@/types/agentConfig";

/**
 * Shared "currently active agent" for the whole app.
 *
 * Before this provider existed, `AgentConfigPage` held the form-edited
 * agent in a local `useState` and `ConversationalChat` hardcoded
 * `JOHN_DOE_AGENT`, so loading a custom agent on the config page never
 * reached the chat surface — Christoph + Carl reported this on Discord
 * 2026-05-24 as a midterm blocker.
 *
 * Mirrors the existing `ThemeProvider` pattern (lazy-init from
 * localStorage, persist on change) so saved choices survive route
 * navigation AND hard reloads.
 */

type ActiveAgentState = {
  agent: AgentConfig;
  loadedConfigId: string | null;
  setActiveAgent: (agent: AgentConfig, loadedConfigId: string | null) => void;
  resetActiveAgent: () => void;
};

const STORAGE_KEY = "taskorbit-active-agent";

const initialState: ActiveAgentState = {
  agent: JOHN_DOE_AGENT,
  loadedConfigId: null,
  setActiveAgent: () => null,
  resetActiveAgent: () => null,
};

const ActiveAgentContext = createContext<ActiveAgentState>(initialState);

type Persisted = {
  agent: AgentConfig;
  loadedConfigId: string | null;
};

function normalizeStoredAgent(agent: AgentConfig): AgentConfig {
  return {
    ...agent,
    instructions: agent.instructions ?? "",
    first_message: agent.first_message ?? { type: "text", message: "", prompt: "" },
    tools: agent.tools ?? [],
    variables: agent.variables ?? {},
    engine: agent.engine ?? {},
    workflow_dependencies: agent.workflow_dependencies ?? [],
    allowed_handoffs: agent.allowed_handoffs ?? [],
  };
}

function readFromStorage(): Persisted | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Persisted>;
    if (!parsed.agent) return null;
    return {
      agent: normalizeStoredAgent(parsed.agent),
      loadedConfigId: parsed.loadedConfigId ?? null,
    };
  } catch {
    // Storage unavailable (incognito) or corrupt JSON — fall through to defaults.
    return null;
  }
}

export function ActiveAgentProvider({ children }: { children: ReactNode }) {
  const [agent, setAgent] = useState<AgentConfig>(() => {
    return readFromStorage()?.agent ?? JOHN_DOE_AGENT;
  });
  const [loadedConfigId, setLoadedConfigId] = useState<string | null>(() => {
    return readFromStorage()?.loadedConfigId ?? null;
  });

  // On mount: load the default user agent from the backend if localStorage
  // has no saved choice. Falls back silently to JOHN_DOE_AGENT if the API
  // is unreachable (e.g. backend not running locally).
  useEffect(() => {
    if (readFromStorage()) return; // user already has a saved choice
    const controller = new AbortController();
    fetchUserAgents(controller.signal)
      .then((entries) => {
        const defaultEntry = entries.find((e) => e.is_default) ?? entries[0];
        if (defaultEntry) {
          setAgent(backendToFrontendAgent(defaultEntry));
          setLoadedConfigId(`ua:${defaultEntry.template_id ?? defaultEntry.id}`);
        }
      })
      .catch(() => {
        // Backend unavailable — keep JOHN_DOE_AGENT as fallback.
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ agent, loadedConfigId }));
    } catch {
      // Storage unavailable — preference won't persist this session.
    }
  }, [agent, loadedConfigId]);

  const value: ActiveAgentState = {
    agent,
    loadedConfigId,
    setActiveAgent: (nextAgent, nextLoadedConfigId) => {
      setAgent(nextAgent);
      setLoadedConfigId(nextLoadedConfigId);
    },
    resetActiveAgent: () => {
      setAgent(JOHN_DOE_AGENT);
      setLoadedConfigId(null);
    },
  };

  return <ActiveAgentContext.Provider value={value}>{children}</ActiveAgentContext.Provider>;
}

export const useActiveAgent = () => {
  const context = useContext(ActiveAgentContext);
  if (context === undefined) {
    throw new Error("useActiveAgent must be used within an ActiveAgentProvider");
  }
  return context;
};
