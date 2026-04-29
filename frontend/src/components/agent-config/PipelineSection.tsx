import { useId } from "react";
import { Brain, Mic, Volume2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type { AgentConfig } from "@/types/agentConfig";

type Value = Pick<AgentConfig, "stt" | "tts" | "llm">;

type Props = {
  value: Value;
  onChange: (next: Value) => void;
};

function StageHeader({ icon: Icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <FieldLegend variant="label" className="flex items-center gap-2">
      <Icon className="size-4 text-muted-foreground" aria-hidden />
      {label}
    </FieldLegend>
  );
}

export function PipelineSection({ value, onChange }: Props) {
  const idSttModel = useId();
  const idLlmModel = useId();
  const idTtsModel = useId();
  const idTtsVoice = useId();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Brain className="size-4 text-muted-foreground" aria-hidden />
          Pipeline
        </CardTitle>
        <CardDescription>
          Speech-to-text, the language model, and text-to-speech. Switch the
          providers or models without touching code.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 sm:grid-cols-3">
        {/* STT */}
        <FieldSet>
          <StageHeader icon={Mic} label="Speech-to-text" />
          <FieldGroup className="gap-4">
            <Field>
              <FieldLabel>Provider</FieldLabel>
              <Select
                value={value.stt.provider}
                onValueChange={(v) =>
                  onChange({ ...value, stt: { ...value.stt, provider: v as "deepgram" } })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="deepgram">Deepgram</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor={idSttModel}>Model</FieldLabel>
              <Input
                id={idSttModel}
                value={value.stt.model}
                onChange={(e) => onChange({ ...value, stt: { ...value.stt, model: e.target.value } })}
                placeholder="nova-3"
                className="font-mono text-sm"
              />
            </Field>
          </FieldGroup>
        </FieldSet>

        {/* LLM */}
        <FieldSet>
          <StageHeader icon={Brain} label="LLM" />
          <FieldGroup className="gap-4">
            <Field>
              <FieldLabel>Provider</FieldLabel>
              <Select
                value={value.llm.provider}
                onValueChange={(v) =>
                  onChange({
                    ...value,
                    llm: { ...value.llm, provider: v as "openai" | "gemini" },
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="openai">OpenAI</SelectItem>
                    <SelectItem value="gemini">Gemini</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor={idLlmModel}>Model</FieldLabel>
              <Input
                id={idLlmModel}
                value={value.llm.model}
                onChange={(e) => onChange({ ...value, llm: { ...value.llm, model: e.target.value } })}
                placeholder="gpt-4.1-mini"
                className="font-mono text-sm"
              />
            </Field>
          </FieldGroup>
        </FieldSet>

        {/* TTS */}
        <FieldSet>
          <StageHeader icon={Volume2} label="Text-to-speech" />
          <FieldGroup className="gap-4">
            <Field>
              <FieldLabel>Provider</FieldLabel>
              <Select
                value={value.tts.provider}
                onValueChange={(v) =>
                  onChange({ ...value, tts: { ...value.tts, provider: v as "elevenlabs" } })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="elevenlabs">ElevenLabs</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor={idTtsModel}>Model</FieldLabel>
              <Input
                id={idTtsModel}
                value={value.tts.model}
                onChange={(e) => onChange({ ...value, tts: { ...value.tts, model: e.target.value } })}
                placeholder="eleven_turbo_v2"
                className="font-mono text-sm"
              />
            </Field>
            <Field>
              <FieldLabel htmlFor={idTtsVoice}>Voice ID</FieldLabel>
              <Input
                id={idTtsVoice}
                value={value.tts.voice_id}
                onChange={(e) =>
                  onChange({ ...value, tts: { ...value.tts, voice_id: e.target.value } })
                }
                placeholder="rachel"
                className="font-mono text-sm"
              />
            </Field>
          </FieldGroup>
        </FieldSet>
      </CardContent>
    </Card>
  );
}
