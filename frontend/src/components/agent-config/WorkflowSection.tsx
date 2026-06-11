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

import { listAgentConfigs } from "@/lib/agentConfigApi";
import type { SavedAgentConfigSummary } from "@/lib/agentConfigApi";

type Props = {
  workflowDependencies?: string[];
  allowedHandoffs?: string[];
  onWorkflowDependenciesChange: (next: string[]) => void;
  onAllowedHandoffsChange: (next: string[]) => void;
};

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
  agents: SavedAgentConfigSummary[];
  onChange: (next: string[]) => void;
  icon: LucideIcon;
  label: string;
};

function AgentListEditor({ ids, agents, onChange, icon, label }: AgentListEditorProps) {
  const [pending, setPending] = useState("");

  const available = agents.filter((a) => !ids.includes(a.id));

  function add() {
    if (!pending || ids.includes(pending)) return;
    onChange([...ids, pending]);
    setPending("");
  }

  function remove(id: string) {
    onChange(ids.filter((x) => x !== id));
  }

  const nameOf = (id: string) => agents.find((a) => a.id === id)?.name ?? id;

  return (
    <FieldSet>
      <SectionHeader icon={icon} label={label} />
      <FieldGroup className="gap-4">
        <Field>
          <FieldLabel>Add agent</FieldLabel>
          <div className="flex gap-2">
            <Select
              value={pending}
              onValueChange={setPending}
              disabled={available.length === 0}
            >
              <SelectTrigger className="min-w-0 flex-1">
                <SelectValue placeholder="Select an agent…" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {available.map((a) => (
                    <SelectItem key={a.id} value={a.id}>
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
              disabled={!pending}
              onClick={add}
            >
              Add
            </Button>
          </div>
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

export function WorkflowSection({
  workflowDependencies,
  allowedHandoffs,
  onWorkflowDependenciesChange,
  onAllowedHandoffsChange,
}: Props) {
  const deps = workflowDependencies ?? [];
  const handoffs = allowedHandoffs ?? [];

  const [agents, setAgents] = useState<SavedAgentConfigSummary[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    listAgentConfigs(controller.signal)
      .then(setAgents)
      .catch((err: unknown) => {
        if (err instanceof Error && err.name !== "AbortError") {
          console.error("Failed to load agent list:", err);
        }
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
          onChange={onWorkflowDependenciesChange}
          icon={GitFork}
          label="Prerequisite Steps"
        />
        <AgentListEditor
          ids={handoffs}
          agents={agents}
          onChange={onAllowedHandoffsChange}
          icon={ArrowRightLeft}
          label="Allowed Handoffs"
        />
      </CardContent>
    </Card>
  );
}
