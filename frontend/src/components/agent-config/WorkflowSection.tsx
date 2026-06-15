import { useEffect, useState } from "react";
import { ArrowRightLeft, GitFork, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { listAgentConfigs, loadAgentConfig } from "@/lib/agentConfigApi";
import { getWorkflowValidationError, wouldCreateCycle } from "@/lib/workflowValidation";

// ── Types ────────────────────────────────────────────────────────────────────

type Props = {
  workflowDependencies?: string[];
  allowedHandoffs?: string[];
  onWorkflowDependenciesChange: (next: string[]) => void;
  onAllowedHandoffsChange: (next: string[]) => void;
  /** Logical agent_id of the config currently being edited — used to detect cycles. */
  currentAgentId?: string;
  onValidationChange?: (state: WorkflowValidationState) => void;
};

/** Resolved from each saved config's blob: logical id + display name. */
type AgentOption = { agentId: string; name: string };

export type WorkflowValidationState = {
  valid: boolean;
  error: string | null;
};

// ── Shared sub-components ────────────────────────────────────────────────────

function SectionHeader({ icon: Icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <FieldLegend variant="label" className="flex items-center gap-2">
      <Icon className="size-4 text-muted-foreground" aria-hidden />
      {label}
    </FieldLegend>
  );
}

type AgentListEditorProps = {
  ids: string[];
  agents: AgentOption[];
  loading: boolean;
  onChange: (next: string[]) => void;
  icon: LucideIcon;
  label: string;
  /** When provided alongside depGraph, cycle detection is active. */
  currentAgentId?: string;
  depGraph?: Map<string, string[]>;
  /** Inline error from a blocked Add attempt — also blocks save until cleared. */
  externalError?: string | null;
  onAddBlocked?: (message: string | null) => void;
};

function AgentListEditor({
  ids,
  agents,
  loading,
  onChange,
  icon,
  label,
  currentAgentId,
  depGraph,
  externalError,
  onAddBlocked,
}: AgentListEditorProps) {
  const [pending, setPending] = useState("");

  const displayError = externalError;

  // Only agents not already in this list appear in the dropdown.
  const available = agents.filter((a) => !ids.includes(a.agentId));

  function handleValueChange(v: string) {
    setPending(v);
    onAddBlocked?.(null);
  }

  function add() {
    if (!pending || ids.includes(pending)) return;

    if (currentAgentId && depGraph) {
      if (pending === currentAgentId) {
        onAddBlocked?.("An agent cannot depend on itself.");
        return;
      }
      if (wouldCreateCycle(pending, depGraph, currentAgentId)) {
        onAddBlocked?.("Adding this agent would create a circular dependency.");
        return;
      }
    }

    onAddBlocked?.(null);
    onChange([...ids, pending]);
    setPending("");
  }

  function remove(id: string) {
    onAddBlocked?.(null);
    onChange(ids.filter((x) => x !== id));
  }

  const nameOf = (id: string) => agents.find((a) => a.agentId === id)?.name ?? id;

  return (
    <FieldSet>
      <SectionHeader icon={icon} label={label} />
      <FieldGroup className="gap-4">
        <Field>
          <FieldLabel>Add agent</FieldLabel>
          <div className="flex gap-2">
            <Select
              value={pending}
              onValueChange={handleValueChange}
              disabled={loading || available.length === 0}
            >
              <SelectTrigger className="min-w-0 flex-1">
                <SelectValue
                  placeholder={
                    loading
                      ? "Loading agents…"
                      : available.length === 0
                        ? "No agents available"
                        : "Select an agent…"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {available.map((a) => (
                    <SelectItem key={a.agentId} value={a.agentId}>
                      {a.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={loading || !pending}
              onClick={add}
            >
              Add
            </Button>
          </div>
          {displayError !== null && (
            <p className="mt-1 text-sm text-destructive">{displayError}</p>
          )}
        </Field>
        {ids.length > 0 && (
          <Field>
            <FieldLabel>Selected</FieldLabel>
            <div className="flex flex-wrap gap-2">
              {ids.map((id) => (
                <Badge key={id} variant="secondary" className="gap-1 pr-1">
                  {nameOf(id)}
                  <button
                    type="button"
                    onClick={() => remove(id)}
                    className="ml-1 rounded-full p-0.5 hover:bg-foreground/10"
                    aria-label={`Remove ${nameOf(id)}`}
                  >
                    <X className="size-3" />
                  </button>
                </Badge>
              ))}
            </div>
          </Field>
        )}
      </FieldGroup>
    </FieldSet>
  );
}

// ── Exported component ───────────────────────────────────────────────────────

export function WorkflowSection({
  workflowDependencies,
  allowedHandoffs,
  onWorkflowDependenciesChange,
  onAllowedHandoffsChange,
  currentAgentId,
  onValidationChange,
}: Props) {
  const deps = workflowDependencies ?? [];
  const handoffs = allowedHandoffs ?? [];

  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [depGraph, setDepGraph] = useState<Map<string, string[]>>(new Map());
  const [loading, setLoading] = useState(true);
  const [pendingAddError, setPendingAddError] = useState<string | null>(null);

  const savedDepsError = getWorkflowValidationError(currentAgentId, deps, depGraph);
  const workflowError = pendingAddError ?? savedDepsError;

  useEffect(() => {
    onValidationChange?.({ valid: workflowError === null, error: workflowError });
  }, [workflowError, onValidationChange]);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    setLoading(true);

    listAgentConfigs(signal)
      .then(async (summaries) => {
        // Load every agent's full config blob in parallel so we have both
        // their logical agent_id (the value the backend uses in dependencies)
        // and their own workflow_dependencies (needed to build the dep graph).
        const fullConfigs = await Promise.all(
          summaries.map((s) => loadAgentConfig(s.id, signal)),
        );

        const optionsMap = new Map<string, string>();
        const graph = new Map<string, string[]>();

        for (const saved of fullConfigs) {
          const c = saved.config as {
            agent_id?: string;
            name?: string;
            workflow_dependencies?: string[];
          };
          const agentId = c.agent_id;
          if (!agentId) continue; // skip malformed entries

          // Deduplicate: if we already saw this agentId, skip adding to options
          // but still update the graph (though they should have the same deps).
          if (!optionsMap.has(agentId)) {
            optionsMap.set(agentId, c.name ?? saved.name);
          }
          graph.set(agentId, c.workflow_dependencies ?? []);
        }

        const options: AgentOption[] = Array.from(optionsMap.entries()).map(([agentId, name]) => ({
          agentId,
          name,
        }));

        setAgents(options);
        setDepGraph(graph);
      })
      .catch((err: unknown) => {
        if (err instanceof Error && err.name !== "AbortError") {
          console.error("Failed to load agent list:", err);
        }
      })
      .finally(() => {
        // Only clear the loading state when the fetch was NOT aborted — if it
        // was aborted the component is unmounting and the state update is moot.
        if (!signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GitFork className="size-4 text-muted-foreground" aria-hidden />
          Workflow
        </CardTitle>
        <CardDescription>
          Define which agents must finish before this one starts and where this agent may hand off
          the conversation.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 sm:grid-cols-2">
        <AgentListEditor
          ids={deps}
          agents={agents}
          loading={loading}
          onChange={(next) => {
            setPendingAddError(null);
            onWorkflowDependenciesChange(next);
          }}
          icon={GitFork}
          label="Prerequisite Steps"
          currentAgentId={currentAgentId}
          depGraph={depGraph}
          externalError={workflowError}
          onAddBlocked={setPendingAddError}
        />
        <AgentListEditor
          ids={handoffs}
          agents={agents}
          loading={loading}
          onChange={onAllowedHandoffsChange}
          icon={ArrowRightLeft}
          label="Allowed Handoffs"
        />
      </CardContent>
    </Card>
  );
}
