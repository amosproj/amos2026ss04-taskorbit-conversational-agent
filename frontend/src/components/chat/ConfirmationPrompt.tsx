import { Check, ShieldCheck, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { ConfirmationPromptState } from "@/types/callState";

type Props = {
  prompt: ConfirmationPromptState;
  onApprove: () => void;
  onDeny: () => void;
};

/**
 * Inline mid-call confirmation. Architecture §4.1 mandates explicit user
 * approval for sensitive actions; this is the surface that captures the
 * approval. Renders in place of the normal CallControls when the agent
 * has paused on a tool decision.
 */
export function ConfirmationPrompt({ prompt, onApprove, onDeny }: Props) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-4 py-4">
        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground"
          >
            <ShieldCheck className="size-4" />
          </span>
          <div className="flex min-w-0 flex-col gap-1">
            <p className="text-sm font-medium">
              The agent is asking before it acts
            </p>
            <p className="text-sm text-muted-foreground">{prompt.prompt}</p>
            <p className="font-mono text-xs text-muted-foreground">
              tool: {prompt.tool_name}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onDeny} type="button">
            <X data-icon="inline-start" />
            Deny
          </Button>
          <Button size="sm" onClick={onApprove} type="button">
            <Check data-icon="inline-start" />
            Approve
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
