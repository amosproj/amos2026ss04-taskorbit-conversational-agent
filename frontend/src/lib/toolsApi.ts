/**
 * Client for POST /api/v1/tools/try. Runs an external_api tool config once so
 * the config UI can show the live response without a conversation (#229).
 */

export type ToolTryResult = {
  success: boolean;
  elapsed_ms: number;
  data: Record<string, unknown>;
};

export async function tryTool(
  parameters: Record<string, unknown>,
  args: Record<string, unknown>,
): Promise<ToolTryResult> {
  const res = await fetch("/api/v1/tools/try", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ parameters, args }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail ?? `HTTP ${res.status}`));
  }
  return res.json() as Promise<ToolTryResult>;
}
