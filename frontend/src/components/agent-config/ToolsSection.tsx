import { useState } from "react";
import { ArrowRightLeft, Globe, PhoneOff, Plus, Trash2, Wrench } from "lucide-react";
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
  END_CALL_DEFAULT_DESCRIPTION,
  emptyToolByType,
  type AgentTransferTool,
  type DataExtractionTool,
  type EndCallTool,
  type ExternalApiTool,
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
  external_api: {
    label: "External API",
    icon: Globe,
    blurb: "Call any HTTP API or outbound webhook through configuration alone.",
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
              Functions the LLM can invoke during a call — capture data, end the call, or hand off
              to another agent.
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
        ) : tool.type === "agent_transfer" ? (
          <AgentTransferEditor tool={tool} onChange={onChange} />
        ) : (
          <ExternalApiEditor tool={tool} onChange={onChange} />
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
          placeholder={END_CALL_DEFAULT_DESCRIPTION}
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

  // Safe fallback: Prevents the UI from crashing with a "Cannot read properties of undefined (reading 'length')"
  // error if the backend data is malformed or missing the targets array.
  const targets = Array.isArray(tool.targets) ? tool.targets : [];

  const addTarget = () => {
    const t = draft.trim();
    if (!t || targets.includes(t)) {
      setDraft("");
      return;
    }
    onChange({ ...tool, targets: [...targets, t] });
    setDraft("");
  };

  const removeTarget = (target: string) => {
    onChange({ ...tool, targets: targets.filter((t) => t !== target) });
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
          {targets.length > 0 ? (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {targets.map((target) => (
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

/* ──────────────────────────────────────────────────────────────────── */
/* external_api (#66)                                                   */
/* ──────────────────────────────────────────────────────────────────── */

const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;
type HttpMethod = (typeof HTTP_METHODS)[number];

type ExternalApiParameters = {
  request: {
    method: HttpMethod;
    url: string;
    headers?: Record<string, string>;
    query?: Record<string, string>;
    body?: unknown;
    timeout_seconds?: number;
  };
  response: { extract?: Record<string, string> };
  auth: { allowed_env: string[] };
  error_mapping: Record<string, string>;
  args_schema: Record<string, unknown>;
};

function readParameters(tool: ExternalApiTool): ExternalApiParameters {
  // The stored shape is Record<string, unknown> so this normalises every
  // optional sub-object into a present default for the form to bind to.
  const p = tool.parameters as Partial<ExternalApiParameters>;
  const request = (p.request ?? {}) as Partial<ExternalApiParameters["request"]>;
  const response = (p.response ?? {}) as Partial<ExternalApiParameters["response"]>;
  const auth = (p.auth ?? {}) as Partial<ExternalApiParameters["auth"]>;
  return {
    request: {
      method: (request.method as HttpMethod) ?? "GET",
      url: request.url ?? "",
      headers: request.headers ?? {},
      query: request.query ?? {},
      body: request.body,
      timeout_seconds: request.timeout_seconds,
    },
    response: { extract: response.extract ?? {} },
    auth: { allowed_env: auth.allowed_env ?? [] },
    error_mapping: p.error_mapping ?? {},
    args_schema: p.args_schema ?? { type: "object", properties: {} },
  };
}

function writeParameters(tool: ExternalApiTool, params: ExternalApiParameters): ExternalApiTool {
  return { ...tool, parameters: params as unknown as Record<string, unknown> };
}

/** Editor for a `name -> value` map. */
function KeyValueEditor({
  label,
  value,
  onChange,
  keyPlaceholder,
  valuePlaceholder,
}: {
  label: string;
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
  keyPlaceholder: string;
  valuePlaceholder: string;
}) {
  const entries = Object.entries(value);

  const updateKey = (oldKey: string, newKey: string) => {
    if (newKey === oldKey) return;
    const next: Record<string, string> = {};
    for (const [k, v] of entries) next[k === oldKey ? newKey : k] = v;
    onChange(next);
  };
  const updateValue = (key: string, val: string) => {
    onChange({ ...value, [key]: val });
  };
  const removeRow = (key: string) => {
    const next = { ...value };
    delete next[key];
    onChange(next);
  };
  const addRow = () => {
    // Pick a non-colliding placeholder key so the new row renders immediately.
    let suffix = 1;
    let candidate = "key";
    while (candidate in value) {
      suffix += 1;
      candidate = `key${suffix}`;
    }
    onChange({ ...value, [candidate]: "" });
  };

  return (
    <Field>
      <div className="mb-2 flex items-center justify-between gap-3">
        <FieldLabel>{label}</FieldLabel>
        <Button variant="outline" size="sm" onClick={addRow} type="button">
          <Plus data-icon="inline-start" />
          Add
        </Button>
      </div>
      {entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">None.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {entries.map(([k, v]) => (
            <li
              key={k}
              className="grid gap-2 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_auto] sm:items-center"
            >
              <Input
                value={k}
                onChange={(e) => updateKey(k, e.target.value)}
                placeholder={keyPlaceholder}
                className="font-mono text-sm"
                aria-label={`${label} key`}
              />
              <Input
                value={v}
                onChange={(e) => updateValue(k, e.target.value)}
                placeholder={valuePlaceholder}
                className="font-mono text-sm"
                aria-label={`${label} value`}
              />
              <Button
                variant="ghost"
                size="icon"
                onClick={() => removeRow(k)}
                aria-label={`Remove ${k}`}
                type="button"
                className="text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="size-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Field>
  );
}

function ExternalApiEditor({
  tool,
  onChange,
}: {
  tool: ExternalApiTool;
  onChange: (next: ExternalApiTool) => void;
}) {
  const params = readParameters(tool);
  const update = (next: ExternalApiParameters) => onChange(writeParameters(tool, next));

  // Body and args_schema are edited as raw JSON so callers can express
  // arbitrary structure without the form locking them into a shape.
  // Local string state lets the user type freely; we only push valid JSON
  // back into the stored config on each change. Parse errors surface
  // inline rather than corrupting the saved value.
  const [bodyText, setBodyText] = useState<string>(() =>
    params.request.body === undefined ? "" : JSON.stringify(params.request.body, null, 2),
  );
  const [bodyError, setBodyError] = useState<string>("");
  const [schemaText, setSchemaText] = useState<string>(() =>
    JSON.stringify(params.args_schema, null, 2),
  );
  const [schemaError, setSchemaError] = useState<string>("");
  const [envDraft, setEnvDraft] = useState<string>("");

  const setRequest = (patch: Partial<ExternalApiParameters["request"]>) =>
    update({ ...params, request: { ...params.request, ...patch } });

  const onBodyBlur = () => {
    const trimmed = bodyText.trim();
    if (trimmed === "") {
      setBodyError("");
      setRequest({ body: undefined });
      return;
    }
    try {
      const parsed = JSON.parse(trimmed);
      setBodyError("");
      setRequest({ body: parsed });
    } catch (err) {
      setBodyError((err as Error).message);
    }
  };

  const onSchemaBlur = () => {
    const trimmed = schemaText.trim();
    if (trimmed === "") {
      setSchemaError("");
      update({ ...params, args_schema: { type: "object", properties: {} } });
      return;
    }
    try {
      const parsed = JSON.parse(trimmed);
      setSchemaError("");
      update({ ...params, args_schema: parsed as Record<string, unknown> });
    } catch (err) {
      setSchemaError((err as Error).message);
    }
  };

  const addEnv = () => {
    const trimmed = envDraft.trim();
    if (!trimmed || params.auth.allowed_env.includes(trimmed)) {
      setEnvDraft("");
      return;
    }
    update({ ...params, auth: { allowed_env: [...params.auth.allowed_env, trimmed] } });
    setEnvDraft("");
  };
  const removeEnv = (name: string) => {
    update({
      ...params,
      auth: { allowed_env: params.auth.allowed_env.filter((e) => e !== name) },
    });
  };

  return (
    <FieldGroup className="gap-4">
      <Field>
        <FieldLabel>Tool name</FieldLabel>
        <Input
          value={tool.name}
          onChange={(e) => onChange({ ...tool, name: e.target.value })}
          placeholder="call_external_api"
          className="font-mono text-sm"
        />
      </Field>
      <Field>
        <FieldLabel>Description</FieldLabel>
        <Textarea
          value={tool.description}
          onChange={(e) => onChange({ ...tool, description: e.target.value })}
          rows={2}
          placeholder="Look up a weather forecast for the supplied city."
        />
      </Field>

      <div className="grid gap-4 sm:grid-cols-[minmax(0,8rem)_minmax(0,1fr)_minmax(0,8rem)]">
        <Field>
          <FieldLabel>Method</FieldLabel>
          <Select
            value={params.request.method}
            onValueChange={(v) => setRequest({ method: v as HttpMethod })}
          >
            <SelectTrigger aria-label="HTTP method">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {HTTP_METHODS.map((m) => (
                  <SelectItem key={m} value={m}>
                    {m}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
        <Field>
          <FieldLabel>URL</FieldLabel>
          <Input
            value={params.request.url}
            onChange={(e) => setRequest({ url: e.target.value })}
            placeholder="https://api.example.com/v1/widgets/{{args.id}}"
            className="font-mono text-sm"
          />
        </Field>
        <Field>
          <FieldLabel>Timeout (s)</FieldLabel>
          <Input
            type="number"
            min={1}
            value={params.request.timeout_seconds ?? ""}
            onChange={(e) =>
              setRequest({
                timeout_seconds: e.target.value === "" ? undefined : Number(e.target.value),
              })
            }
            placeholder="10"
          />
        </Field>
      </div>

      <KeyValueEditor
        label="Headers"
        value={params.request.headers ?? {}}
        onChange={(headers) => setRequest({ headers })}
        keyPlaceholder="X-API-Key"
        valuePlaceholder="{{env.MY_KEY}}"
      />
      <KeyValueEditor
        label="Query params"
        value={params.request.query ?? {}}
        onChange={(query) => setRequest({ query })}
        keyPlaceholder="city"
        valuePlaceholder="{{args.city}}"
      />

      <Field>
        <FieldLabel>Request body (JSON)</FieldLabel>
        <Textarea
          value={bodyText}
          onChange={(e) => setBodyText(e.target.value)}
          onBlur={onBodyBlur}
          rows={4}
          placeholder='{"name": "{{args.name}}"}'
          className="font-mono text-xs"
        />
        {bodyError ? <p className="mt-1 text-xs text-destructive">{bodyError}</p> : null}
      </Field>

      <KeyValueEditor
        label="Response extract (name → dot-path)"
        value={params.response.extract ?? {}}
        onChange={(extract) => update({ ...params, response: { extract } })}
        keyPlaceholder="temperature"
        valuePlaceholder="data.current.temp_c"
      />

      <Field>
        <FieldLabel>Allowed env vars</FieldLabel>
        <div className="flex gap-2">
          <Input
            value={envDraft}
            onChange={(e) => setEnvDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addEnv();
              }
            }}
            placeholder="MY_API_KEY"
            className="font-mono text-sm"
            aria-label="Add allowed env var"
          />
          <Button variant="outline" size="sm" onClick={addEnv} type="button">
            <Plus data-icon="inline-start" />
            Add
          </Button>
        </div>
        {params.auth.allowed_env.length > 0 ? (
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {params.auth.allowed_env.map((name) => (
              <li key={name}>
                <Badge variant="secondary" className="gap-1.5 font-mono">
                  {name}
                  <button
                    type="button"
                    onClick={() => removeEnv(name)}
                    className="-mr-1 inline-flex size-4 items-center justify-center rounded text-muted-foreground hover:text-destructive"
                    aria-label={`Remove env ${name}`}
                  >
                    <Trash2 className="size-3" />
                  </button>
                </Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-xs text-muted-foreground">
            Templates that reference {"{{env.X}}"} must list X here.
          </p>
        )}
      </Field>

      <KeyValueEditor
        label="Error mapping (code → message)"
        value={params.error_mapping}
        onChange={(error_mapping) => update({ ...params, error_mapping })}
        keyPlaceholder="HTTP_4XX"
        valuePlaceholder="The CRM could not find that record."
      />

      <Field>
        <FieldLabel>Args schema (JSON)</FieldLabel>
        <Textarea
          value={schemaText}
          onChange={(e) => setSchemaText(e.target.value)}
          onBlur={onSchemaBlur}
          rows={5}
          placeholder='{"type":"object","required":["city"],"properties":{"city":{"type":"string"}}}'
          className="font-mono text-xs"
        />
        {schemaError ? <p className="mt-1 text-xs text-destructive">{schemaError}</p> : null}
      </Field>
    </FieldGroup>
  );
}
