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
  /** Translates a persisted entry (which may be a row ref, not an agent_id)
   * to the logical agent_id depGraph is keyed by. Identity by default. */
  resolveAgentId: (dep: string) => string = (dep) => dep,
): string | null {
  if (!currentAgentId?.trim()) return null;

  for (const dep of workflowDependencies) {
    const agentId = resolveAgentId(dep);
    if (agentId === currentAgentId) {
      return "An agent cannot depend on itself.";
    }
    if (depGraph.size > 0 && wouldCreateCycle(agentId, depGraph, currentAgentId)) {
      return "This workflow would create a circular dependency.";
    }
  }
  return null;
}
