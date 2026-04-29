import { ArrowRightLeft, PhoneOff, Wrench } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { ToolFiring } from "@/lib/mockConversations";

type Props = { firing: ToolFiring };

type MarkerVisual = {
  Icon: LucideIcon;
  summary: string;
};

function visualForFiring(firing: ToolFiring): MarkerVisual {
  switch (firing.type) {
    case "data_extraction": {
      const fieldCount = Object.keys(firing.values).length;
      const summary =
        fieldCount === 1 ? "saved 1 field" : `saved ${fieldCount} fields`;
      return { Icon: Wrench, summary };
    }
    case "end_call":
      return { Icon: PhoneOff, summary: "ended the call" };
    case "agent_transfer":
      return {
        Icon: ArrowRightLeft,
        summary: `handed off to ${firing.target}`,
      };
  }
}

/**
 * Inline system-event marker rendered between transcript turns at the
 * point a tool was invoked. Sits visually between bubbles to tell the
 * "when" of the firing without forcing the reader to cross-reference a
 * separate timeline card.
 */
export function TranscriptToolMarker({ firing }: Props) {
  const { Icon, summary } = visualForFiring(firing);
  return (
    <li
      className="flex items-center gap-2 py-1 text-xs text-muted-foreground"
      aria-label={`Tool call: ${firing.tool_name}, ${summary}`}
    >
      <span aria-hidden className="h-px flex-1 bg-border" />
      <span className="flex items-center gap-1.5 rounded-full border bg-muted/40 px-2.5 py-0.5">
        <Icon aria-hidden className="size-3" />
        <span className="font-mono">{firing.tool_name}</span>
        <span>·</span>
        <span>{summary}</span>
      </span>
      <span aria-hidden className="h-px flex-1 bg-border" />
    </li>
  );
}
