import { useId } from "react";
import { ScrollText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldSeparator,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

import type { FirstMessage } from "@/types/agentConfig";

type Value = { instructions: string; first_message: FirstMessage };

type Props = {
  value: Value;
  onChange: (next: Value) => void;
  showErrors?: boolean;
};

export function InstructionsSection({ value, onChange, showErrors }: Props) {
  const idInstructions = useId();
  const idFirstMessage = useId();
  const idFirstPrompt = useId();

  const instructionsInvalid = showErrors && !value.instructions.trim();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ScrollText className="size-4 text-muted-foreground" aria-hidden />
          Instructions & first message
        </CardTitle>
        <CardDescription>
          Persona, role, and guardrails the agent follows on every call,
          plus the exact greeting it opens with.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup>
          <Field data-invalid={instructionsInvalid || undefined}>
            <FieldLabel htmlFor={idInstructions}>Instructions</FieldLabel>
            <Textarea
              id={idInstructions}
              value={value.instructions}
              onChange={(e) => onChange({ ...value, instructions: e.target.value })}
              rows={10}
              placeholder="# PERSONA&#10;# ROLE&#10;# GUARDRAILS&#10;..."
              className="font-mono text-sm leading-relaxed"
              aria-invalid={instructionsInvalid || undefined}
            />
            <FieldDescription>
              Persona, role, and guardrails for the agent. Markdown headings
              are common but not required.
            </FieldDescription>
            {instructionsInvalid ? (
              <FieldError>Instructions are required.</FieldError>
            ) : null}
          </Field>

          <FieldSeparator>First message</FieldSeparator>

          <Field>
            <FieldLabel htmlFor={idFirstMessage}>
              <span>Greeting message</span>
              <Badge variant="secondary" className="ml-2 font-normal">
                {value.first_message.type}
              </Badge>
            </FieldLabel>
            <Textarea
              id={idFirstMessage}
              value={value.first_message.message}
              onChange={(e) =>
                onChange({
                  ...value,
                  first_message: { ...value.first_message, message: e.target.value },
                })
              }
              rows={3}
              placeholder="Hi there! I'm…"
            />
            <FieldDescription>
              The exact text the agent says first. Spoken via TTS at call start.
            </FieldDescription>
          </Field>

          <Field data-disabled>
            <FieldLabel htmlFor={idFirstPrompt}>Prompt (reserved)</FieldLabel>
            <Input
              id={idFirstPrompt}
              value={value.first_message.prompt}
              onChange={(e) =>
                onChange({
                  ...value,
                  first_message: { ...value.first_message, prompt: e.target.value },
                })
              }
              disabled
              placeholder="(empty for type=text)"
            />
            <FieldDescription>
              Reserved for future first-message types (e.g. dynamic). Empty when
              the type is plain text.
            </FieldDescription>
          </Field>
        </FieldGroup>
      </CardContent>
    </Card>
  );
}
