import { useEffect, useState } from "react";

import { fetchUserAgents, type UserAgentEntry } from "@/lib/userAgentsApi";
import { cn } from "@/lib/utils";

/**
 * Home-screen agent switcher: a chip row of every available agent (built-in
 * templates + user copies). The active agent is marked; clicking a chip
 * promotes that agent to the featured quick-start via `onSelect`. Renders
 * nothing until there is more than one agent to choose from.
 */
export function AgentSwitcher({
  activeAgentId,
  activeAgentName,
  onSelect,
  className,
}: {
  activeAgentId: string;
  activeAgentName: string;
  onSelect: (entry: UserAgentEntry) => void;
  className?: string;
}) {
  const [agents, setAgents] = useState<UserAgentEntry[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    fetchUserAgents(controller.signal)
      .then(setAgents)
      .catch(() => {
        // Backend unavailable, the switcher simply stays hidden.
      });
    return () => controller.abort();
  }, []);

  // The built-in template and the user's copy of an agent share one
  // config.agent_id, so collapse by agent_id to show each logical agent once.
  // A row is "the active one" only when BOTH its agent_id and its name match the
  // featured agent; agent_id alone is ambiguous because a template and its
  // renamed copy share it (that ambiguity is what lit up two chips). User copies
  // are listed before templates, so keeping the FIRST active match lets a renamed
  // copy win over its template and keeps the chip label in sync with the featured
  // card. (Two genuinely-distinct agents sharing an agent_id would collapse,
  // which is rare, and the data model does not guarantee agent_id uniqueness.)
  const idOf = (e: UserAgentEntry) => e.config.agent_id ?? e.config.id ?? e.id;
  const isActiveRow = (e: UserAgentEntry) =>
    idOf(e) === activeAgentId && e.name === activeAgentName;

  const byAgent = new Map<string, UserAgentEntry>();
  for (const entry of agents) {
    const existing = byAgent.get(idOf(entry));
    if (!existing || (isActiveRow(entry) && !isActiveRow(existing))) {
      byAgent.set(idOf(entry), entry);
    }
  }
  const uniqueAgents = [...byAgent.values()];

  if (uniqueAgents.length <= 1) return null;

  return (
    <div className={cn("space-y-3", className)}>
      <p className="text-sm font-medium">Switch agent</p>
      <div className="flex flex-wrap gap-2">
        {uniqueAgents.map((entry) => {
          const isActive = idOf(entry) === activeAgentId;
          return (
            <button
              key={entry.id}
              type="button"
              onClick={() => onSelect(entry)}
              aria-pressed={isActive}
              className={cn(
                "rounded-full border px-3 py-1 text-sm transition-colors",
                isActive
                  ? "border-primary bg-primary/10 font-medium text-primary"
                  : "border-border text-muted-foreground hover:bg-muted/50 hover:text-foreground",
              )}
            >
              {entry.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}
