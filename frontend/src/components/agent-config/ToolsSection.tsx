import { useState } from "react";
import { ArrowRightLeft, PhoneOff, Plus, Trash2, Wrench } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Empty } from "@/components/Empty";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

import {
  emptyToolByType,
  type AgentTransferTool,
  type DataExtractionTool,
  type EndCallTool,
  type ParamType,
  type ToolDefinition,
  type ToolParam,
  type ToolType,
} from "@/types/agentConfig";

type Props = {
  value: ToolDefinition[];
  onChange: (next: ToolDefinition[]) => void;
};

const PARAM_TYPES: ParamType[] = ["string", "number", "boolean", "date"];

const TOOL_TYPE_META: Record<ToolType, { label: string; icon: LucideIcon; blurb: string }> = {
  data_extraction: {
    label: "Data extraction",
    icon: Wrench,
    blurb: "Capture structured data the LLM hears during the call.",
  },
  end_call: {
    label: "End call",
    icon: PhoneOff,
    blurb: "Let the agent gracefully hang up when the goal is met.",
  },
  agent_transfer: {
    label: "Agent transfer",
    icon: ArrowRightLeft,
    blurb: "Hand off the conversation to a different agent (e.g. tech support).",
  },
};

export function ToolsSection({ value, onChange }: Props) {
  const [pendingType, setPendingType] = useState<ToolType>("data_extraction");

  const updateTool = (index: number, next: ToolDefinition) => {
    onChange(value.map((t, i) => (i === index ? next : t)));
  };

  const removeTool = (index: number) => {
    onChange(value.filter((_, i) => i !== index));
  };

  const addTool = () => {
    onChange([...value, emptyToolByType(pendingType)]);
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1.5">
            <CardTitle className="flex items-center gap-2">
              <Wrench className="size-4 text-muted-foreground" aria-hidden />
              Tools
            </CardTitle>
            <CardDescription>
              Functions the LLM can invoke during a call — capture data, end
              the call, or hand off to another agent.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Select value={pendingType} onValueChange={(v) => setPendingType(v as ToolType)}>
              <SelectTrigger className="w-[10rem]" aria-label="Tool type to add">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {(Object.keys(TOOL_TYPE_META) as ToolType[]).map((t) => (
                    <SelectItem key={t} value={t}>
                      {TOOL_TYPE_META[t].label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" onClick={addTool} type="button">
              <Plus data-icon="inline-start" />
              Add tool
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {value.length === 0 ? (
          <Empty
            icon={Wrench}
            title="No tools yet"
            description="Pick a tool type above and click Add tool to get started."
          />
        ) : (
          value.map((tool, ti) => (
            <ToolCard
              key={ti}
              tool={tool}
              onChange={(next) => updateTool(ti, next)}
              onRemove={() => removeTool(ti)}
            />
          ))
        )}
      </CardContent>
    </Card>
  );
}

function ToolCard({
  tool,
  onChange,
  onRemove,
}: {
  tool: ToolDefinition;
  onChange: (next: ToolDefinition) => void;
  onRemove: () => void;
}) {
  const meta = TOOL_TYPE_META[tool.type];
  const Icon = meta.icon;

  return (
    <div className="rounded-lg border border-dashed border-border bg-muted/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon className="size-4 text-muted-foreground" aria-hidden />
          <Badge variant="outline" className="font-mono text-xs">
            {tool.type}
          </Badge>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onRemove}
          aria-label="Remove tool"
          type="button"
          className="text-muted-foreground hover:text-destructive"
        >
          <Trash2 className="size-4" />
        </Button>
      </div>

      <p className="mt-2 text-sm text-muted-foreground">{meta.blurb}</p>

      <div className="mt-4">
        {tool.type === "data_extraction" ? (
          <DataExtractionEditor tool={tool} onChange={onChange} />
        ) : tool.type === "end_call" ? (
          <EndCallEditor tool={tool} onChange={onChange} />
        ) : (
          <AgentTransferEditor tool={tool} onChange={onChange} />
        )}
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────── */
/* data_extraction                                                      */
/* ──────────────────────────────────────────────────────────────────── */

function emptyParam(): ToolParam {
  return { variable_name: "", description: "", type: "string", required: false };
}

function DataExtractionEditor({
  tool,
  onChange,
}: {
  tool: DataExtractionTool;
  onChange: (next: DataExtractionTool) => void;
}) {
  const updateParam = (pi: number, next: ToolParam) => {
    onChange({ ...tool, params: tool.params.map((p, i) => (i === pi ? next : p)) });
  };
  const removeParam = (pi: number) => {
    onChange({ ...tool, params: tool.params.filter((_, i) => i !== pi) });
  };
  const addParam = () => {
    onChange({ ...tool, params: [...tool.params, emptyParam()] });
  };

  return (
    <>
      <FieldGroup className="gap-4">
        <Field>
          <FieldLabel>Tool name</FieldLabel>
          <Input
            value={tool.name}
            onChange={(e) => onChange({ ...tool, name: e.target.value })}
            placeholder="collect_user_info"
            className="font-mono text-sm"
          />
        </Field>
        <Field>
          <FieldLabel>Description</FieldLabel>
          <Textarea
            value={tool.description}
            onChange={(e) => onChange({ ...tool, description: e.target.value })}
            rows={2}
            placeholder="Use this tool to save customer information…"
          />
        </Field>
      </FieldGroup>

      <div className="mt-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h4 className="text-sm font-medium">Params</h4>
          <Button variant="outline" size="sm" onClick={addParam} type="button">
            <Plus data-icon="inline-start" />
            Add param
          </Button>
        </div>

        {tool.params.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No params yet. Add one to capture data from the conversation.
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {tool.params.map((param, pi) => (
              <li
                key={pi}
                className="grid gap-3 rounded-md border bg-background p-3 sm:grid-cols-[minmax(0,9rem)_minmax(0,7rem)_minmax(0,1fr)_auto_auto] sm:items-center"
              >
                <Input
                  value={param.variable_name}
                  onChange={(e) => updateParam(pi, { ...param, variable_name: e.target.value })}
                  placeholder="full_name"
                  className="font-mono text-sm"
                  aria-label="Variable name"
                />
                <Select
                  value={param.type}
                  onValueChange={(v) => updateParam(pi, { ...param, type: v as ParamType })}
                >
                  <SelectTrigger aria-label="Param type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {PARAM_TYPES.map((t) => (
                        <SelectItem key={t} value={t}>
                          {t}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <Input
                  value={param.description}
                  onChange={(e) => updateParam(pi, { ...param, description: e.target.value })}
                  placeholder="Customer's full name"
                  aria-label="Param description"
                />
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Switch
                    checked={param.required}
                    onCheckedChange={(c) => updateParam(pi, { ...param, required: c })}
                    aria-label="Required"
                  />
                  required
                </label>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => removeParam(pi)}
                  aria-label="Remove param"
                  type="button"
                  className="text-muted-foreground hover:text-destructive"
                >
                  <Trash2 className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

/* ──────────────────────────────────────────────────────────────────── */
/* end_call                                                             */
/* ──────────────────────────────────────────────────────────────────── */

function EndCallEditor({
  tool,
  onChange,
}: {
  tool: EndCallTool;
  onChange: (next: EndCallTool) => void;
}) {
  return (
    <FieldGroup className="gap-4">
      <Field>
        <FieldLabel>Tool name</FieldLabel>
        <Input
          value={tool.name}
          onChange={(e) => onChange({ ...tool, name: e.target.value })}
          placeholder="end_call"
          className="font-mono text-sm"
        />
      </Field>
      <Field>
        <FieldLabel>Description</FieldLabel>
        <Textarea
          value={tool.description}
          onChange={(e) => onChange({ ...tool, description: e.target.value })}
          rows={2}
          placeholder="End the conversation when the goal is met."
        />
      </Field>
    </FieldGroup>
  );
}

/* ──────────────────────────────────────────────────────────────────── */
/* agent_transfer                                                       */
/* ──────────────────────────────────────────────────────────────────── */

function AgentTransferEditor({
  tool,
  onChange,
}: {
  tool: AgentTransferTool;
  onChange: (next: AgentTransferTool) => void;
}) {
  const [draft, setDraft] = useState("");

  const addTarget = () => {
    const t = draft.trim();
    if (!t || tool.targets.includes(t)) {
      setDraft("");
      return;
    }
    onChange({ ...tool, targets: [...tool.targets, t] });
    setDraft("");
  };

  const removeTarget = (target: string) => {
    onChange({ ...tool, targets: tool.targets.filter((t) => t !== target) });
  };

  return (
    <>
      <FieldGroup className="gap-4">
        <Field>
          <FieldLabel>Tool name</FieldLabel>
          <Input
            value={tool.name}
            onChange={(e) => onChange({ ...tool, name: e.target.value })}
            placeholder="transfer_to_agent"
            className="font-mono text-sm"
          />
        </Field>
        <Field>
          <FieldLabel>Description</FieldLabel>
          <Textarea
            value={tool.description}
            onChange={(e) => onChange({ ...tool, description: e.target.value })}
            rows={2}
            placeholder="Hand off the conversation to a specialised agent."
          />
        </Field>
        <Field>
          <FieldLabel>Target agents</FieldLabel>
          <div className="flex gap-2">
            <Input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addTarget();
                }
              }}
              placeholder="emergency-line-agent"
              className="font-mono text-sm"
              aria-label="Add target agent ID"
            />
            <Button variant="outline" size="sm" onClick={addTarget} type="button">
              <Plus data-icon="inline-start" />
              Add
            </Button>
          </div>
          {tool.targets.length > 0 ? (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {tool.targets.map((target) => (
                <li key={target}>
                  <Badge variant="secondary" className="gap-1.5 font-mono">
                    {target}
                    <button
                      type="button"
                      onClick={() => removeTarget(target)}
                      className="-mr-1 inline-flex size-4 items-center justify-center rounded text-muted-foreground hover:text-destructive"
                      aria-label={`Remove target ${target}`}
                    >
                      <Trash2 className="size-3" />
                    </button>
                  </Badge>
                </li>
              ))}
            </ul>
          ) : null}
        </Field>
      </FieldGroup>
    </>
  );
}
