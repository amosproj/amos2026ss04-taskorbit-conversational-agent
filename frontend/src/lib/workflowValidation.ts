/**
 * Workflow dependency validation — shared by WorkflowSection and AgentConfigPage.
 */

export function wouldCreateCycle(
  from: string,
  depGraph: Map<string, string[]>,
  target: string,
  visited = new Set<string>(),
): boolean {
  if (from === target) return true;
  if (visited.has(from)) return false;
  visited.add(from);
  return (depGraph.get(from) ?? []).some((n) => wouldCreateCycle(n, depGraph, target, visited));
}

export function getWorkflowValidationError(
  currentAgentId: string | undefined,
  workflowDependencies: string[],
  depGraph: Map<string, string[]>,
): string | null {
  if (!currentAgentId?.trim()) return null;

  for (const dep of workflowDependencies) {
    if (dep === currentAgentId) {
      return "An agent cannot depend on itself.";
    }
    if (depGraph.size > 0 && wouldCreateCycle(dep, depGraph, currentAgentId)) {
      return "This workflow would create a circular dependency.";
    }
  }
  return null;
}
