import { useId, useState } from "react";
import { ShieldCheck, Plus, Trash2 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";

import type { PersonaConstraints } from "@/types/agentConfig";

type Props = {
  value: PersonaConstraints | undefined;
  onChange: (next: PersonaConstraints | undefined) => void;
};

export function PersonaGuardrailsSection({ value, onChange }: Props) {
  const idSwitch = useId();
  const idScope = useId();
  const idOutOfScope = useId();
  const idRefusal = useId();

  const enabled = !!value;
  const [tagDraft, setTagDraft] = useState("");

  const toggle = (next: boolean) =>
    onChange(next ? (value ?? { scope: "", out_of_scope: [], refusal_template: "" }) : undefined);

  const addTag = () => {
    if (!value) return;
    const t = tagDraft.trim();
    if (!t) return;
    if (value.out_of_scope && value.out_of_scope.includes(t)) {
      setTagDraft("");
      return;
    }
    onChange({ ...value, out_of_scope: [...(value.out_of_scope ?? []), t] });
    setTagDraft("");
  };

  const removeTag = (tag: string) => {
    if (!value) return;
    onChange({ ...value, out_of_scope: (value.out_of_scope ?? []).filter((t) => t !== tag) });
  };

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="size-4 text-muted-foreground" aria-hidden />
          Persona guardrails
        </CardTitle>
        <CardDescription>
          Optional scope and refusal settings keep the agent in role and redirect off-topic
          requests.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between">
          <div className="text-sm text-muted-foreground">Enable persona guardrails</div>
          <Switch
            id={idSwitch}
            checked={enabled}
            onCheckedChange={toggle}
            aria-label="Enable persona guardrails"
          />
        </div>

        {enabled && value ? (
          <div className="mt-4">
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor={idScope}>Authorized scope</FieldLabel>
                <Input
                  id={idScope}
                  value={value.scope ?? ""}
                  onChange={(e) => onChange({ ...value, scope: e.target.value })}
                  placeholder="E.g., Product & ordering questions for TechStore"
                />
                <FieldDescription>
                  Short 1-2 sentence description of what this agent handles.
                </FieldDescription>
              </Field>

              <Field>
                <FieldLabel htmlFor={idOutOfScope}>Forbidden topics</FieldLabel>
                <div className="flex gap-2">
                  <Input
                    id={idOutOfScope}
                    value={tagDraft}
                    onChange={(e) => setTagDraft(e.target.value)}
                    placeholder="Add a forbidden topic (e.g., 'medical advice')"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addTag();
                      }
                    }}
                  />
                  <Button variant="outline" size="sm" onClick={addTag} type="button">
                    <Plus /> Add
                  </Button>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {(value.out_of_scope ?? []).map((t) => (
                    <Badge key={t} variant="secondary" className="gap-2 font-mono">
                      <span>{t}</span>
                      <button
                        type="button"
                        onClick={() => removeTag(t)}
                        className="-mr-1 inline-flex size-4 items-center justify-center rounded text-muted-foreground hover:text-destructive"
                        aria-label={`Remove ${t}`}
                      >
                        <Trash2 className="size-3" />
                      </button>
                    </Badge>
                  ))}
                </div>
                <FieldDescription>
                  Topics the agent MUST politely refuse and redirect to a different channel.
                </FieldDescription>
              </Field>

              <Field>
                <FieldLabel htmlFor={idRefusal}>Refusal template</FieldLabel>
                <Textarea
                  id={idRefusal}
                  value={value.refusal_template ?? ""}
                  onChange={(e) => onChange({ ...value, refusal_template: e.target.value })}
                  placeholder="I'm here to help with TechStore questions — I can't assist with that topic."
                  rows={3}
                />
                <FieldDescription>
                  Exact phrase the agent should use to refuse and redirect.
                </FieldDescription>
              </Field>
            </FieldGroup>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
