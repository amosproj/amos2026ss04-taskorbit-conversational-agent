import { useId } from "react";
import { Brain, Mic, Volume2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";

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

import {
  LLM_MODELS,
  LLM_MODEL_DEFAULTS,
  STT_MODELS,
  STT_MODEL_DEFAULT,
  TTS_MODELS,
  TTS_MODEL_DEFAULT,
  TTS_VOICES,
  withCurrent,
} from "@/lib/pipelineOptions";
import type { AgentConfig, LlmProvider, SttProvider, TtsProvider } from "@/types/agentConfig";

type Value = Pick<AgentConfig, "stt" | "tts" | "llm">;

type Props = {
  value: Value;
  onChange: (next: Value) => void;
};

// Each provider speaks only its own model names; pairing e.g. gemini with
// gpt-4o-mini reaches the voice path and 404s mid-call (ticket #99). Switching
// provider resets the model to that provider's default so a mismatch can't be
// authored in the first place. The model lists themselves live in
// pipelineOptions.ts — the single source of truth (ticket #87).

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

  // withCurrent keeps a legacy / env-default value selectable even when it
  // isn't one of the curated options (AC5).
  const sttModels = withCurrent(STT_MODELS[value.stt.provider], value.stt.model);
  const llmModels = withCurrent(LLM_MODELS[value.llm.provider], value.llm.model);
  const ttsModels = withCurrent(TTS_MODELS[value.tts.provider], value.tts.model);
  // A voice_id not in TTS_VOICES is rendered as an extra option showing the raw id.
  const voiceIsKnown = TTS_VOICES.some((v) => v.id === value.tts.voice_id);

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
                onValueChange={(v) =>
                  onChange({
                    ...value,
                    stt: { provider: v as SttProvider, model: STT_MODEL_DEFAULT },
                  })
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
              <Select
                value={value.stt.model}
                onValueChange={(v) => onChange({ ...value, stt: { ...value.stt, model: v } })}
              >
                <SelectTrigger id={idSttModel} className="font-mono text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {sttModels.map((m) => (
                      <SelectItem key={m} value={m} className="font-mono text-sm">
                        {m}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
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
              <Select
                value={value.llm.model}
                onValueChange={(v) => onChange({ ...value, llm: { ...value.llm, model: v } })}
              >
                <SelectTrigger id={idLlmModel} className="font-mono text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {llmModels.map((m) => (
                      <SelectItem key={m} value={m} className="font-mono text-sm">
                        {m}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
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
                  onChange({
                    ...value,
                    tts: { ...value.tts, provider: v as TtsProvider, model: TTS_MODEL_DEFAULT },
                  })
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
              <Select
                value={value.tts.model}
                onValueChange={(v) => onChange({ ...value, tts: { ...value.tts, model: v } })}
              >
                <SelectTrigger id={idTtsModel} className="font-mono text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {ttsModels.map((m) => (
                      <SelectItem key={m} value={m} className="font-mono text-sm">
                        {m}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor={idTtsVoice}>Voice</FieldLabel>
              <Select
                value={value.tts.voice_id}
                onValueChange={(v) => onChange({ ...value, tts: { ...value.tts, voice_id: v } })}
              >
                <SelectTrigger id={idTtsVoice}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {TTS_VOICES.map((voice) => (
                      <SelectItem key={voice.id} value={voice.id}>
                        {voice.name}
                      </SelectItem>
                    ))}
                    {/* Legacy / unlisted voice id — show the raw id so it round-trips (AC5). */}
                    {!voiceIsKnown && value.tts.voice_id ? (
                      <SelectItem value={value.tts.voice_id} className="font-mono text-sm">
                        {value.tts.voice_id}
                      </SelectItem>
                    ) : null}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          </FieldGroup>
        </FieldSet>
      </CardContent>
    </Card>
  );
}
