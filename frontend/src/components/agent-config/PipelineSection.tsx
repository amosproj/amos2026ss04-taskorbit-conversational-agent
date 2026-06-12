import { useId } from "react";
import { Brain, Mic, Volume2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type { AgentConfig, LlmProvider, SttProvider, TtsProvider } from "@/types/agentConfig";

type Value = Pick<AgentConfig, "stt" | "tts" | "llm">;

type Props = {
  value: Value;
  onChange: (next: Value) => void;
};

// Each LLM provider speaks only its own model names; pairing e.g. gemini with
// gpt-4o-mini reaches the voice path and 404s mid-call (ticket #99). Switching
// provider resets the model to that provider's default so a mismatch can't be
// authored in the first place.
const LLM_MODEL_DEFAULTS: Record<LlmProvider, string> = {
  openai: "gpt-4o-mini",
  gemini: "gemini-2.5-flash",
};

// Same reset-on-switch rule for STT/TTS (#135). The elevenlabs STT default
// must stay scribe_v2_realtime: it is the only Scribe model the voice
// worker's streaming turn handling supports (batch models are rejected by
// the backend factory and fall back to it anyway).
const STT_MODEL_DEFAULTS: Record<SttProvider, string> = {
  deepgram: "nova-3",
  elevenlabs: "scribe_v2_realtime",
};

// Deepgram Aura encodes the voice in the model name (aura-2-<voice>-en),
// so the Voice ID field only applies to ElevenLabs.
const TTS_MODEL_DEFAULTS: Record<TtsProvider, string> = {
  elevenlabs: "eleven_multilingual_v2",
  deepgram: "aura-2-andromeda-en",
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
          Speech-to-text, the language model, and text-to-speech. Switch the providers or models
          without touching code.
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
                onValueChange={(v) => {
                  const provider = v as SttProvider;
                  onChange({
                    ...value,
                    stt: { ...value.stt, provider, model: STT_MODEL_DEFAULTS[provider] },
                  });
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="deepgram">Deepgram</SelectItem>
                    <SelectItem value="elevenlabs">ElevenLabs</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor={idSttModel}>Model</FieldLabel>
              <Input
                id={idSttModel}
                value={value.stt.model}
                onChange={(e) =>
                  onChange({ ...value, stt: { ...value.stt, model: e.target.value } })
                }
                placeholder={STT_MODEL_DEFAULTS[value.stt.provider]}
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
                onValueChange={(v) => {
                  const provider = v as LlmProvider;
                  onChange({
                    ...value,
                    llm: { provider, model: LLM_MODEL_DEFAULTS[provider] },
                  });
                }}
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
                onChange={(e) =>
                  onChange({ ...value, llm: { ...value.llm, model: e.target.value } })
                }
                placeholder="gpt-4o-mini"
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
                onValueChange={(v) => {
                  const provider = v as TtsProvider;
                  onChange({
                    ...value,
                    tts: { ...value.tts, provider, model: TTS_MODEL_DEFAULTS[provider] },
                  });
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="elevenlabs">ElevenLabs</SelectItem>
                    <SelectItem value="deepgram">Deepgram</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor={idTtsModel}>Model</FieldLabel>
              <Input
                id={idTtsModel}
                value={value.tts.model}
                onChange={(e) =>
                  onChange({ ...value, tts: { ...value.tts, model: e.target.value } })
                }
                placeholder={TTS_MODEL_DEFAULTS[value.tts.provider]}
                className="font-mono text-sm"
              />
            </Field>
            {value.tts.provider === "elevenlabs" && (
              <Field>
                <FieldLabel htmlFor={idTtsVoice}>Voice ID</FieldLabel>
                <Input
                  id={idTtsVoice}
                  value={value.tts.voice_id}
                  onChange={(e) =>
                    onChange({ ...value, tts: { ...value.tts, voice_id: e.target.value } })
                  }
                  placeholder="JBFqnCBsd6RMkjVDRZzb"
                  className="font-mono text-sm"
                />
              </Field>
            )}
          </FieldGroup>
        </FieldSet>
      </CardContent>
    </Card>
  );
}
