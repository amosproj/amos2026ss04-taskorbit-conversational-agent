import { useMemo, useState } from "react";
import { Plus, Trash2, Variable } from "lucide-react";

import { Empty } from "@/components/Empty";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type Props = {
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
};

type Row = { id: number; key: string; value: string };

let rowSeq = 0;

function recordToRows(record: Record<string, string>): Row[] {
  return Object.entries(record).map(([k, v]) => ({ id: rowSeq++, key: k, value: v }));
}

function rowsToRecord(rows: Row[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of rows) {
    const k = r.key.trim();
    if (k) out[k] = r.value;
  }
  return out;
}

/**
 * VariablesSection — edits a Record<string,string> via a stable list of
 * rows (typing into the key field shouldn't refocus the input, which it
 * would if we keyed by `key` directly). We hold rows in local state and
 * push the derived record up on every change.
 */
export function VariablesSection({ value, onChange }: Props) {
  // Initialise rows from the incoming record once. Subsequent external
  // resets (Load preset / Reset) replace `value` and we re-derive.
  const [rows, setRows] = useState<Row[]>(() => recordToRows(value));

  // Detect external resets by stringify comparison and re-sync rows.
  const externalKey = useMemo(() => JSON.stringify(value), [value]);
  const [lastExternalKey, setLastExternalKey] = useState(externalKey);
  if (externalKey !== lastExternalKey) {
    // Compare against current local rows; if they don't reconcile, accept the
    // external value as the new source of truth.
    const derivedFromRows = JSON.stringify(rowsToRecord(rows));
    if (derivedFromRows !== externalKey) {
      setRows(recordToRows(value));
    }
    setLastExternalKey(externalKey);
  }

  const updateRow = (id: number, patch: Partial<Row>) => {
    setRows((prev) => {
      const next = prev.map((r) => (r.id === id ? { ...r, ...patch } : r));
      onChange(rowsToRecord(next));
      return next;
    });
  };

  const removeRow = (id: number) => {
    setRows((prev) => {
      const next = prev.filter((r) => r.id !== id);
      onChange(rowsToRecord(next));
      return next;
    });
  };

  const addRow = () => {
    setRows((prev) => [...prev, { id: rowSeq++, key: "", value: "" }]);
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1.5">
            <CardTitle className="flex items-center gap-2">
              <Variable className="size-4 text-muted-foreground" aria-hidden />
              Variables
            </CardTitle>
            <CardDescription>
              Templating values the orchestrator can interpolate into
              instructions and tool calls.
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={addRow} type="button">
            <Plus data-icon="inline-start" />
            Add variable
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <Empty
            icon={Variable}
            title="No variables yet"
            description="Add a key/value pair (e.g. name = John Doe) to make it available to the agent at runtime."
          />
        ) : (
          <ul className="flex flex-col gap-2">
            {rows.map((row) => (
              <li
                key={row.id}
                className="grid gap-2 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_auto] sm:items-center"
              >
                <Input
                  value={row.key}
                  onChange={(e) => updateRow(row.id, { key: e.target.value })}
                  placeholder="key"
                  className="font-mono text-sm"
                  aria-label="Variable key"
                />
                <Input
                  value={row.value}
                  onChange={(e) => updateRow(row.id, { value: e.target.value })}
                  placeholder="value"
                  aria-label="Variable value"
                />
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => removeRow(row.id)}
                  aria-label="Remove variable"
                  type="button"
                  className="text-muted-foreground hover:text-destructive"
                >
                  <Trash2 className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
