import { useId } from "react";
import { Bot } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";

type IdentityValue = { agent_id: string; name: string };

type Props = {
  value: IdentityValue;
  onChange: (next: IdentityValue) => void;
  showErrors?: boolean;
};

export function IdentitySection({ value, onChange, showErrors }: Props) {
  const idAgentId = useId();
  const idName = useId();

  const agentIdInvalid = showErrors && !value.agent_id.trim();
  const nameInvalid = showErrors && !value.name.trim();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bot className="size-4 text-muted-foreground" aria-hidden />
          Identity
        </CardTitle>
        <CardDescription>
          How the agent identifies itself in logs and to the orchestration layer.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <Field data-invalid={agentIdInvalid || undefined}>
            <FieldLabel htmlFor={idAgentId}>Agent ID</FieldLabel>
            <Input
              id={idAgentId}
              value={value.agent_id}
              onChange={(e) => onChange({ ...value, agent_id: e.target.value })}
              placeholder="preet-agent"
              className="font-mono text-sm"
              aria-invalid={agentIdInvalid || undefined}
              autoComplete="off"
              spellCheck={false}
            />
            <FieldDescription>
              Stable identifier used by the backend. Lowercase letters and
              hyphens recommended.
            </FieldDescription>
            {agentIdInvalid ? <FieldError>Agent ID is required.</FieldError> : null}
          </Field>

          <Field data-invalid={nameInvalid || undefined}>
            <FieldLabel htmlFor={idName}>Display name</FieldLabel>
            <Input
              id={idName}
              value={value.name}
              onChange={(e) => onChange({ ...value, name: e.target.value })}
              placeholder="John Doe"
              aria-invalid={nameInvalid || undefined}
            />
            <FieldDescription>
              Friendly name presented to end users in transcripts and history.
            </FieldDescription>
            {nameInvalid ? <FieldError>Display name is required.</FieldError> : null}
          </Field>
        </FieldGroup>
      </CardContent>
    </Card>
  );
}
