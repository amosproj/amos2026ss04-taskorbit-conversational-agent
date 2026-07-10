import { useEffect, useState } from "react";
import { ArrowRightLeft, GitFork, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

import { listAgentConfigs, loadAgentConfig } from "@/lib/agentConfigApi";
import { fetchUserAgents, type UserAgentEntry } from "@/lib/userAgentsApi";
import {
  buildSimpleWorkflowRules,
  isSimpleWorkflowRules,
  parseSimpleWorkflowRules,
} from "@/lib/workflowRules";
import { getWorkflowValidationError, wouldCreateCycle } from "@/lib/workflowValidation";

import type { WorkflowRule } from "@/types/agentConfig";

// ── Types ────────────────────────────────────────────────────────────────────

type Props = {
  workflowDependencies?: string[];
  workflowRules?: WorkflowRule[];
  allowedHandoffs?: string[];
  onWorkflowDependenciesChange: (next: string[]) => void;
  onWorkflowRulesChange: (next: WorkflowRule[] | undefined) => void;
  onAllowedHandoffsChange: (next: string[]) => void;
  /** Logical agent_id of the config currently being edited — used to detect cycles. */
  currentAgentId?: string;
  /** User agents from Agent Config (refreshed after Save as new). */
  userAgentEntries?: UserAgentEntry[];
  onValidationChange?: (state: WorkflowValidationState) => void;
};

/** One row per saved config — rowId disambiguates entries that share an
 * agent_id (e.g. two customized copies of one template). */
type AgentOption = { rowId: string; agentId: string; name: string; isCustomized: boolean };

export type WorkflowValidationState = {
  valid: boolean;
  error: string | null;
};

type ConfigBlob = {
  agent_id?: string;
  id?: string;
  name?: string;
  workflow_dependencies?: string[];
};

function logicalAgentId(c: ConfigBlob): string | undefined {
  const id = (c.agent_id ?? c.id ?? "").trim();
  return id || undefined;
}

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
  // Tracks the selected row, not the agent_id — two rows can share an
  // agent_id, and Radix Select requires each SelectItem's value to be unique
  // or it garbles the displayed label (concatenates every matching item).
  const [pendingRowId, setPendingRowId] = useState("");

  const displayError = externalError;

  // Only agents not already in this list appear in the dropdown.
  const available = agents.filter((a) => !ids.includes(a.agentId));
  const availableSaved = available.filter((a) => a.isCustomized);
  const availableBuiltIn = available.filter((a) => !a.isCustomized);
  const pendingAgentId = available.find((a) => a.rowId === pendingRowId)?.agentId ?? "";

  function handleValueChange(rowId: string) {
    setPendingRowId(rowId);
    onAddBlocked?.(null);
  }

  function add() {
    if (!pendingAgentId || ids.includes(pendingAgentId)) return;

    if (currentAgentId && depGraph) {
      if (pendingAgentId === currentAgentId) {
        onAddBlocked?.("An agent cannot depend on itself.");
        return;
      }
      if (wouldCreateCycle(pendingAgentId, depGraph, currentAgentId)) {
        onAddBlocked?.("Adding this agent would create a circular dependency.");
        return;
      }
    }

    onAddBlocked?.(null);
    onChange([...ids, pendingAgentId]);
    setPendingRowId("");
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
              value={pendingRowId}
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
                {availableSaved.length > 0 && (
                  <SelectGroup>
                    <SelectLabel>Saved agents</SelectLabel>
                    {availableSaved.map((a) => (
                      <SelectItem key={a.rowId} value={a.rowId}>
                        {a.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                )}
                {availableBuiltIn.length > 0 && (
                  <SelectGroup>
                    <SelectLabel>Built-in agents</SelectLabel>
                    {availableBuiltIn.map((a) => (
                      <SelectItem key={a.rowId} value={a.rowId}>
                        {a.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                )}
              </SelectContent>
            </Select>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={loading || !pendingRowId}
              onClick={add}
            >
              Add
            </Button>
          </div>
          {displayError !== null && <p className="mt-1 text-sm text-destructive">{displayError}</p>}
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
  workflowRules,
  allowedHandoffs,
  onWorkflowDependenciesChange,
  onWorkflowRulesChange,
  onAllowedHandoffsChange,
  currentAgentId,
  userAgentEntries,
  onValidationChange,
}: Props) {
  const deps = workflowDependencies ?? [];
  const handoffs = allowedHandoffs ?? [];
  const simpleRules = parseSimpleWorkflowRules(workflowRules);
  const conditionalAdvanced =
    workflowRules !== undefined &&
    workflowRules.length > 0 &&
    !isSimpleWorkflowRules(workflowRules);

  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [depGraph, setDepGraph] = useState<Map<string, string[]>>(new Map());
  const [loading, setLoading] = useState(true);
  const [pendingAddError, setPendingAddError] = useState<string | null>(null);

  const savedWhenAgents = agents.filter((a) => a.isCustomized);
  const builtInWhenAgents = agents.filter((a) => !a.isCustomized);

  const savedDepsError = getWorkflowValidationError(currentAgentId, deps, depGraph);
  const workflowError = pendingAddError ?? savedDepsError;

  useEffect(() => {
    onValidationChange?.({ valid: workflowError === null, error: workflowError });
  }, [workflowError, onValidationChange]);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    setLoading(true);

    async function loadWorkflowAgents() {
      const graph = new Map<string, string[]>();

      // One row per saved config — mirrors the "Load agent" menu, which
      // doesn't dedupe either. Two entries can share an agent_id (e.g. two
      // customized copies of one template), so agentId alone can't be the key.
      const options: AgentOption[] = [];

      // Primary: /v1/user-agents (where "Save as new" writes since #71 fix).
      const userEntries =
        userAgentEntries ?? (await fetchUserAgents(signal).catch(() => [] as UserAgentEntry[]));
      const primaryRowIds = new Set(userEntries.map((entry) => entry.id));
      for (const entry of userEntries) {
        const c = entry.config as ConfigBlob;
        const agentId = logicalAgentId(c);
        if (!agentId) continue;
        options.push({
          rowId: entry.id,
          agentId,
          name: c.name ?? entry.name,
          isCustomized: entry.is_customized,
        });
        graph.set(agentId, c.workflow_dependencies ?? []);
      }

      // Legacy: /v1/agent-configs presets (older saves before user-agents POST path).
      // Its rows overlap with /v1/user-agents by id, so skip any already seen above.
      try {
        const summaries = await listAgentConfigs(signal);
        const fullConfigs = await Promise.all(
          summaries.filter((s) => !primaryRowIds.has(s.id)).map((s) => loadAgentConfig(s.id, signal)),
        );
        for (const saved of fullConfigs) {
          const c = saved.config as ConfigBlob;
          const agentId = logicalAgentId(c);
          if (!agentId) continue;
          options.push({
            rowId: `legacy:${saved.id}`,
            agentId,
            name: c.name ?? saved.name,
            isCustomized: true,
          });
          graph.set(agentId, c.workflow_dependencies ?? []);
        }
      } catch (err: unknown) {
        if (!(err instanceof Error && err.name === "AbortError")) {
          console.error("Failed to load legacy agent-config list:", err);
        }
      }

      setAgents(options);
      setDepGraph(graph);
    }

    void loadWorkflowAgents()
      .catch((err: unknown) => {
        if (err instanceof Error && err.name !== "AbortError") {
          console.error("Failed to load agent list:", err);
        }
      })
      .finally(() => {
        if (!signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [userAgentEntries]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GitFork className="size-4 text-muted-foreground" aria-hidden />
          Workflow
        </CardTitle>
        <CardDescription>
          Define prerequisite steps, conditional branches by routed intent, and allowed handoffs.
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

        <div className="col-span-full space-y-4 border-t pt-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-1">
              <FieldLegend variant="label" className="flex items-center gap-2">
                <GitFork className="size-4 text-muted-foreground" aria-hidden />
                Conditional prerequisites
              </FieldLegend>
              <FieldDescription>
                When enabled, the engine picks prerequisites from these rules after intent routing.
                Static prerequisite steps above are ignored while rules are set.
              </FieldDescription>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                id="conditional-workflow-rules"
                checked={simpleRules.enabled}
                disabled={conditionalAdvanced}
                onCheckedChange={(on) => {
                  if (on) {
                    onWorkflowRulesChange(
                      buildSimpleWorkflowRules(
                        simpleRules.whenAgentName,
                        simpleRules.whenDependencies,
                      ),
                    );
                  } else {
                    onWorkflowRulesChange(undefined);
                  }
                }}
              />
              <FieldLabel htmlFor="conditional-workflow-rules" className="font-normal">
                Use conditional prerequisites
              </FieldLabel>
            </div>
          </div>

          {conditionalAdvanced && (
            <p className="text-sm text-muted-foreground">
              This agent has custom workflow rules that are not editable in the form. Use Copy JSON
              to view them, or turn off conditional rules to replace with the simple editor.
            </p>
          )}

          {simpleRules.enabled && !conditionalAdvanced && (
            <div className="grid gap-6 sm:grid-cols-2">
              <FieldSet>
                <Field>
                  <FieldLabel>When routed to</FieldLabel>
                  <Select
                    value={agents.find((a) => a.agentId === simpleRules.whenAgentName)?.rowId ?? ""}
                    onValueChange={(rowId) => {
                      const match = agents.find((a) => a.rowId === rowId);
                      if (!match) return;
                      onWorkflowRulesChange(
                        buildSimpleWorkflowRules(match.agentId, simpleRules.whenDependencies),
                      );
                    }}
                    disabled={loading || agents.length === 0}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue
                        placeholder={
                          loading
                            ? "Loading agents…"
                            : agents.length === 0
                              ? "No agents available"
                              : "Select an agent…"
                        }
                      />
                    </SelectTrigger>
                    <SelectContent>
                      {savedWhenAgents.length > 0 && (
                        <SelectGroup>
                          <SelectLabel>Saved agents</SelectLabel>
                          {savedWhenAgents.map((a) => (
                            <SelectItem key={a.rowId} value={a.rowId}>
                              {a.name}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      )}
                      {builtInWhenAgents.length > 0 && (
                        <SelectGroup>
                          <SelectLabel>Built-in agents</SelectLabel>
                          {builtInWhenAgents.map((a) => (
                            <SelectItem key={a.rowId} value={a.rowId}>
                              {a.name}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      )}
                    </SelectContent>
                  </Select>
                  <FieldDescription>
                    Matches the agent name after intent routing (e.g. technical support requests).
                  </FieldDescription>
                </Field>
              </FieldSet>
              <AgentListEditor
                ids={simpleRules.whenDependencies}
                agents={agents}
                loading={loading}
                onChange={(whenDependencies) =>
                  onWorkflowRulesChange(
                    buildSimpleWorkflowRules(simpleRules.whenAgentName, whenDependencies),
                  )
                }
                icon={GitFork}
                label="Then run prerequisite steps"
                currentAgentId={currentAgentId}
                depGraph={depGraph}
                onAddBlocked={setPendingAddError}
              />
            </div>
          )}

          {simpleRules.enabled && !conditionalAdvanced && (
            <p className="text-sm text-muted-foreground">
              Otherwise (all other routed intents): no prerequisite steps.
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
