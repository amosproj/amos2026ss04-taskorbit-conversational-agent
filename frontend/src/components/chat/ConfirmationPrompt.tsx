import { Check, GitBranch, ShieldCheck, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ConfirmationPromptState } from "@/types/callState";

type Props = {
  prompt: ConfirmationPromptState;
  onApprove: () => void;
  onDeny: () => void;
};

const TOOL_TYPE_LABELS: Record<string, string> = {
  data_extraction: "Saving information",
  agent_transfer: "Transferring to another agent",
  end_call: "Ending the call",
  external_api: "Calling an external service",
};

/**
 * Inline mid-call confirmation. Architecture §4.1 mandates explicit user
 * approval for sensitive actions; this is the surface that captures the
 * approval. Renders above the in-call input dock while the agent has
 * paused on a tool decision; the input stays visible but disabled.
 */
export function ConfirmationPrompt({ prompt, onApprove, onDeny }: Props) {
  const isWorkflow = prompt.type === "workflow";
  const toolTypeLabel = !isWorkflow && prompt.toolType ? TOOL_TYPE_LABELS[prompt.toolType] : null;

  return (
    <Card className={cn("border-l-4", isWorkflow ? "border-l-primary" : "border-l-amber-500")}>
      <CardContent className="flex flex-col gap-4 py-4">
        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className={cn(
              "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full",
              isWorkflow ? "bg-primary/10 text-primary" : "bg-amber-500/10 text-amber-600",
            )}
          >
            {isWorkflow ? <GitBranch className="size-4" /> : <ShieldCheck className="size-4" />}
          </span>
          <div className="flex min-w-0 flex-col gap-1">
            <p className="text-sm font-medium">
              {isWorkflow ? "Prerequisite step required" : "The agent is asking before it acts"}
            </p>
            {toolTypeLabel && <p className="text-sm font-medium text-amber-600">{toolTypeLabel}</p>}
            <p className="text-sm text-muted-foreground">{prompt.description}</p>
            {!isWorkflow && (
              <p className="font-mono text-[10px] text-muted-foreground uppercase opacity-70">
                action: {prompt.action}
              </p>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onDeny} type="button">
            <X data-icon="inline-start" />
            {isWorkflow ? "Cancel" : "Deny"}
          </Button>
          <Button size="sm" onClick={onApprove} type="button">
            <Check data-icon="inline-start" />
            {isWorkflow ? "Proceed" : "Approve"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
