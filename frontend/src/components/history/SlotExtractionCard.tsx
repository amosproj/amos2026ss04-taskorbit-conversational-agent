import { Badge } from "@/components/ui/badge";
import type { ConversationHistory } from "@/lib/conversationApi";

type SlotExtraction = ConversationHistory["slot_extractions"][number];

function groupByTool(extractions: SlotExtraction[]): Map<string, SlotExtraction[]> {
  const map = new Map<string, SlotExtraction[]>();
  for (const s of extractions) {
    const list = map.get(s.tool_id) ?? [];
    list.push(s);
    map.set(s.tool_id, list);
  }
  return map;
}

type Props = { extractions: SlotExtraction[] };

export function SlotExtractionCard({ extractions }: Props) {
  const byTool = groupByTool(extractions);

  return (
    <dl className="flex flex-col gap-5">
      {[...byTool.entries()].map(([toolId, fields]) => (
        <div key={toolId} className="flex flex-col gap-2">
          <Badge variant="secondary" className="w-fit text-xs font-normal">
            Extracted by: {toolId}
          </Badge>
          <div className="flex flex-col gap-2 pl-1">
            {fields.map((f) => (
              <div key={f.id} className="flex flex-col gap-0.5">
                <dt className="text-xs text-muted-foreground">{f.field_name}</dt>
                <dd className="font-mono text-sm break-all">{f.field_value ?? "—"}</dd>
              </div>
            ))}
          </div>
        </div>
      ))}
    </dl>
  );
}
