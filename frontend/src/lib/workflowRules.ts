/**
 * Helpers for the simplified conditional-workflow UI (Issue #71).
 * Maps one "when routed to X → run prereqs Y, else skip" pattern to workflow_rules.
 */

import type { WorkflowRule } from "@/types/agentConfig";

/** Routed agent names from backend intent → AgentRegistry (orchestration after #8). */
export const ROUTED_AGENT_OPTIONS = [
  { value: "technical_support", label: "Technical Support" },
  { value: "sales", label: "Sales" },
  { value: "general_inquiry", label: "General Inquiry" },
  { value: "customer_dissatisfaction", label: "Customer Dissatisfaction" },
] as const;

export type SimpleWorkflowRulesState = {
  enabled: boolean;
  whenAgentName: string;
  whenDependencies: string[];
};

const DEFAULT_WHEN_AGENT = "technical_support";

/** True when rules match the simple two-branch shape the form edits. */
export function isSimpleWorkflowRules(rules: WorkflowRule[] | undefined): boolean {
  if (!rules?.length) return true;
  if (rules.length !== 2) return false;
  const [first, second] = rules;
  return (
    !first.when.else &&
    !!second.when.else &&
    first.when.agent_name !== undefined &&
    first.when.intent === undefined &&
    (second.dependencies?.length ?? 0) === 0
  );
}

export function parseSimpleWorkflowRules(
  rules: WorkflowRule[] | undefined,
): SimpleWorkflowRulesState {
  if (!rules?.length) {
    return { enabled: false, whenAgentName: DEFAULT_WHEN_AGENT, whenDependencies: [] };
  }

  const conditionRule = rules.find((r) => !r.when.else);
  return {
    enabled: true,
    whenAgentName: conditionRule?.when.agent_name ?? DEFAULT_WHEN_AGENT,
    whenDependencies: conditionRule?.dependencies ?? [],
  };
}

export function buildSimpleWorkflowRules(
  whenAgentName: string,
  whenDependencies: string[],
): WorkflowRule[] {
  return [
    { when: { agent_name: whenAgentName }, dependencies: whenDependencies },
    { when: { else: true }, dependencies: [] },
  ];
}
