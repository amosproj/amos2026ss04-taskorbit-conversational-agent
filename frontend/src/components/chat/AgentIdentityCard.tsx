import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { AgentConfig, ToolDefinition } from "@/types/agentConfig";

type Props = {
  agent: AgentConfig;
  className?: string;
};

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/**
 * Pulls the first non-heading, non-empty line out of the agent's
 * markdown instructions. Used as a one-liner persona summary on the
 * pre-call hero so the user knows who they're about to call without
 * reading the full system prompt.
 */
function describeFromInstructions(instructions: string): string | null {
  for (const raw of instructions.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith("#")) continue;
    if (line.startsWith("-") || line.startsWith("*")) continue;
    if (/^\d+\./.test(line)) continue;
    return line;
  }
  return null;
}

const toolLabels: Record<ToolDefinition["type"], string> = {
  data_extraction: "Data extraction",
  end_call: "End call",
  agent_transfer: "Agent transfer",
};

const languageDisplayNames =
  typeof Intl !== "undefined" && "DisplayNames" in Intl
    ? new Intl.DisplayNames(undefined, { type: "language" })
    : null;

function formatLanguage(tag: string): string {
  return languageDisplayNames?.of(tag) ?? tag.toUpperCase();
}

/**
 * Pre-call hero — surfaces the agent's identity and the JSON config that
 * drives this session so the user (and reviewers) can see the call is
 * connected to the AgentConfig page, not a parallel mock.
 */
export function AgentIdentityCard({ agent, className }: Props) {
  const initials = initialsOf(agent.name);
  const description = describeFromInstructions(agent.instructions);
  const language = agent.language?.default ?? "en";
  const toolTypes = Array.from(new Set(agent.tools.map((t) => t.type)));

  return (
    <Card className={cn("overflow-hidden", className)}>
      <CardHeader className="flex flex-row items-start gap-4 space-y-0">
        <span
          aria-hidden
          className="flex size-12 shrink-0 items-center justify-center rounded-full bg-primary text-base font-semibold text-primary-foreground"
        >
          {initials}
        </span>
        <div className="flex min-w-0 flex-col gap-1">
          <CardTitle className="truncate">{agent.name}</CardTitle>
          {description ? (
            <CardDescription className="line-clamp-2">
              {description}
            </CardDescription>
          ) : null}
        </div>
        <Badge variant="outline" className="shrink-0">
          {formatLanguage(language)}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 border-t pt-4">
        <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
          <div className="flex flex-col gap-0.5">
            <dt className="text-xs text-muted-foreground uppercase tracking-wide">
              STT
            </dt>
            <dd className="font-mono">{agent.stt.provider}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-xs text-muted-foreground uppercase tracking-wide">
              LLM
            </dt>
            <dd className="font-mono">
              {agent.llm.provider} · {agent.llm.model}
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-xs text-muted-foreground uppercase tracking-wide">
              TTS
            </dt>
            <dd className="font-mono">{agent.tts.provider}</dd>
          </div>
        </dl>
        {toolTypes.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Tools:</span>
            {toolTypes.map((type) => (
              <Badge key={type} variant="secondary">
                {toolLabels[type]}
              </Badge>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
