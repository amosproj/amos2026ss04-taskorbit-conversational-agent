import { useId, useState } from "react";
import { ChevronDown, Globe, Plus, Settings2, Trash2, Waves } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";

import type { LanguageConfig, VadConfig } from "@/types/agentConfig";

type Props = {
  language: LanguageConfig | undefined;
  vad: VadConfig | undefined;
  onLanguageChange: (next: LanguageConfig | undefined) => void;
  onVadChange: (next: VadConfig | undefined) => void;
};

const LANGUAGE_DEFAULT: LanguageConfig = {
  default: "en",
  auto_detect: true,
  supported: ["en", "de"],
};

const VAD_DEFAULT: VadConfig = {
  provider: "cerebrio",
  silence_threshold_ms: 500,
};

export function AdvancedSection({ language, vad, onLanguageChange, onVadChange }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <Card className="overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="group flex w-full cursor-pointer items-start justify-between gap-3 text-left transition-colors hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none"
        aria-expanded={open}
        aria-controls="advanced-content"
      >
        <CardHeader className="flex-1 [.group:hover_&]:bg-transparent">
          <div className="space-y-1.5">
            <CardTitle className="flex items-center gap-2">
              <Settings2 className="size-4 text-muted-foreground" aria-hidden />
              Advanced
            </CardTitle>
            <CardDescription>
              Optional language and voice-activity-detection settings. Each
              section is omitted from the saved JSON unless enabled.
            </CardDescription>
          </div>
        </CardHeader>
        <div className="flex shrink-0 items-center gap-2 px-6 pt-6 text-xs font-medium text-muted-foreground transition-colors group-hover:text-foreground">
          <span>{open ? "Hide" : "Show"}</span>
          <ChevronDown
            className={`size-4 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
            aria-hidden
          />
        </div>
      </button>
      {open ? (
        <>
          <Separator />
          <CardContent id="advanced-content" className="flex flex-col gap-6 pt-6">
            <LanguageBlock value={language} onChange={onLanguageChange} />
            <VadBlock value={vad} onChange={onVadChange} />
          </CardContent>
        </>
      ) : null}
    </Card>
  );
}

/* ──────────────────────────────────────────────────────────────────── */
/* Language                                                             */
/* ──────────────────────────────────────────────────────────────────── */

function LanguageBlock({
  value,
  onChange,
}: {
  value: LanguageConfig | undefined;
  onChange: (next: LanguageConfig | undefined) => void;
}) {
  const idSwitch = useId();
  const idDefault = useId();
  const idAuto = useId();
  const enabled = !!value;
  const [draft, setDraft] = useState("");

  const toggle = (next: boolean) => onChange(next ? value ?? LANGUAGE_DEFAULT : undefined);

  const addSupported = () => {
    if (!value) return;
    const t = draft.trim();
    if (!t || value.supported.includes(t)) {
      setDraft("");
      return;
    }
    onChange({ ...value, supported: [...value.supported, t] });
    setDraft("");
  };

  const removeSupported = (code: string) => {
    if (!value) return;
    onChange({ ...value, supported: value.supported.filter((c) => c !== code) });
  };

  return (
    <section className="rounded-lg border border-dashed border-border bg-muted/20 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <h3 className="flex items-center gap-2 text-sm font-medium">
            <Globe className="size-4 text-muted-foreground" aria-hidden />
            Language
          </h3>
          <p className="text-xs text-muted-foreground">
            Default language plus auto-detection for multilingual conversations.
          </p>
        </div>
        <Field orientation="horizontal" className="sm:w-auto">
          <Switch
            id={idSwitch}
            checked={enabled}
            onCheckedChange={toggle}
            aria-label="Enable language config"
          />
          <FieldLabel htmlFor={idSwitch} className="text-sm font-normal">
            Enable
          </FieldLabel>
        </Field>
      </div>

      {enabled && value ? (
        <FieldGroup className="mt-4 gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor={idDefault}>Default language</FieldLabel>
              <Input
                id={idDefault}
                value={value.default}
                onChange={(e) => onChange({ ...value, default: e.target.value })}
                placeholder="en"
                className="font-mono text-sm"
              />
              <FieldDescription>
                ISO code (en, de, fr…). Used as the starting language.
              </FieldDescription>
            </Field>
            <Field orientation="horizontal">
              <Switch
                id={idAuto}
                checked={value.auto_detect}
                onCheckedChange={(c) => onChange({ ...value, auto_detect: c })}
                aria-label="Auto-detect"
              />
              <FieldLabel htmlFor={idAuto} className="text-sm font-normal">
                Auto-detect on call start
              </FieldLabel>
            </Field>
          </div>

          <Field>
            <FieldLabel>Supported languages</FieldLabel>
            <div className="flex gap-2">
              <Input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addSupported();
                  }
                }}
                placeholder="de"
                className="font-mono text-sm"
                aria-label="Add supported language"
              />
              <Button variant="outline" size="sm" onClick={addSupported} type="button">
                <Plus data-icon="inline-start" />
                Add
              </Button>
            </div>
            {value.supported.length > 0 ? (
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {value.supported.map((code) => (
                  <li key={code}>
                    <Badge variant="secondary" className="gap-1.5 font-mono">
                      {code}
                      <button
                        type="button"
                        onClick={() => removeSupported(code)}
                        className="-mr-1 inline-flex size-4 items-center justify-center rounded text-muted-foreground hover:text-destructive"
                        aria-label={`Remove language ${code}`}
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
      ) : null}
    </section>
  );
}

/* ──────────────────────────────────────────────────────────────────── */
/* VAD                                                                  */
/* ──────────────────────────────────────────────────────────────────── */

function VadBlock({
  value,
  onChange,
}: {
  value: VadConfig | undefined;
  onChange: (next: VadConfig | undefined) => void;
}) {
  const idSwitch = useId();
  const idThreshold = useId();
  const enabled = !!value;

  const toggle = (next: boolean) => onChange(next ? value ?? VAD_DEFAULT : undefined);

  return (
    <section className="rounded-lg border border-dashed border-border bg-muted/20 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <h3 className="flex items-center gap-2 text-sm font-medium">
            <Waves className="size-4 text-muted-foreground" aria-hidden />
            Voice activity detection
          </h3>
          <p className="text-xs text-muted-foreground">
            Tunes when the agent treats the caller as having stopped speaking
            so it can respond.
          </p>
        </div>
        <Field orientation="horizontal" className="sm:w-auto">
          <Switch
            id={idSwitch}
            checked={enabled}
            onCheckedChange={toggle}
            aria-label="Enable VAD config"
          />
          <FieldLabel htmlFor={idSwitch} className="text-sm font-normal">
            Enable
          </FieldLabel>
        </Field>
      </div>

      {enabled && value ? (
        <FieldGroup className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field>
            <FieldLabel>Provider</FieldLabel>
            <Select
              value={value.provider}
              onValueChange={(v) =>
                onChange({ ...value, provider: v as VadConfig["provider"] })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="cerebrio">Cerebrio</SelectItem>
                  <SelectItem value="none">None</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor={idThreshold}>Silence threshold (ms)</FieldLabel>
            <Input
              id={idThreshold}
              type="number"
              min={0}
              step={50}
              value={value.silence_threshold_ms}
              onChange={(e) =>
                onChange({
                  ...value,
                  silence_threshold_ms: Number.isNaN(e.target.valueAsNumber)
                    ? 0
                    : e.target.valueAsNumber,
                })
              }
            />
            <FieldDescription>
              How long the user can be silent before the agent considers their
              turn over.
            </FieldDescription>
          </Field>
        </FieldGroup>
      ) : null}
    </section>
  );
}
