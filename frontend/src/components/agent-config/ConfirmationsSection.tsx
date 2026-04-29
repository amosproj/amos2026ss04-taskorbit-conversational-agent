import { useId } from "react";
import { ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";

import type { ConfirmationsConfig, ToolDefinition } from "@/types/agentConfig";

// Default configuration applied when the operator first enables the
// section. `tools: []` means "every tool requires confirmation" — the
// safest starting state.

type Props = {
  value: ConfirmationsConfig | undefined;
  tools: ToolDefinition[];
  onChange: (next: ConfirmationsConfig | undefined) => void;
};

const DEFAULT: ConfirmationsConfig = { required: true, tools: [] };

export function ConfirmationsSection({ value, tools, onChange }: Props) {
  const idEnabled = useId();
  const enabled = !!value;

  const toggleEnabled = (next: boolean) => {
    if (next) onChange(value ?? DEFAULT);
    else onChange(undefined);
  };

  const toggleTool = (toolName: string, on: boolean) => {
    if (!value) return;
    const set = new Set(value.tools);
    if (on) set.add(toolName);
    else set.delete(toolName);
    onChange({ ...value, tools: Array.from(set) });
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1.5">
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-muted-foreground" aria-hidden />
              Confirmations
            </CardTitle>
            <CardDescription>
              Require the agent to confirm with the user before invoking
              tools. The per-tool list narrows the requirement; leave it
              empty to confirm every tool.
            </CardDescription>
          </div>
          <Field orientation="horizontal" className="sm:w-auto">
            <Switch
              id={idEnabled}
              checked={enabled}
              onCheckedChange={toggleEnabled}
              aria-label="Enable confirmations"
            />
            <FieldLabel htmlFor={idEnabled} className="text-sm font-normal">
              Require confirmations
            </FieldLabel>
          </Field>
        </div>
      </CardHeader>
      {enabled ? (
        <CardContent>
          <FieldGroup className="gap-4">
            <Field>
              <FieldLabel>Tools requiring confirmation</FieldLabel>
              <FieldDescription>
                Empty list means every tool requires confirmation. Tick a tool
                to scope the requirement narrower.
              </FieldDescription>
              {tools.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No tools defined yet. Add a tool above to scope confirmations.
                </p>
              ) : (
                <ul className="flex flex-wrap gap-2">
                  {tools.map((tool, i) => {
                    const name = tool.name || `(unnamed ${tool.type})`;
                    const checked = value!.tools.includes(name);
                    return (
                      <li key={`${name}-${i}`}>
                        <label
                          className="flex cursor-pointer items-center gap-2 rounded-md border bg-background px-2.5 py-1.5 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/5"
                        >
                          <Switch
                            checked={checked}
                            onCheckedChange={(c) => toggleTool(name, c)}
                            aria-label={`Require confirmation for ${name}`}
                          />
                          <span className="font-mono text-xs">{name}</span>
                          <Badge variant="outline" className="text-[10px] font-normal">
                            {tool.type}
                          </Badge>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Field>
          </FieldGroup>
        </CardContent>
      ) : null}
    </Card>
  );
}
