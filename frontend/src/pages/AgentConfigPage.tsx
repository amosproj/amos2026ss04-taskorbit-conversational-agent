import { useState } from "react";
import { Copy, FileDown, RotateCcw, Save } from "lucide-react";
import { toast } from "sonner";

import { AdvancedSection } from "@/components/agent-config/AdvancedSection";
import { ConfirmationsSection } from "@/components/agent-config/ConfirmationsSection";
import { IdentitySection } from "@/components/agent-config/IdentitySection";
import { InstructionsSection } from "@/components/agent-config/InstructionsSection";
import { PipelineSection } from "@/components/agent-config/PipelineSection";
import { ToolsSection } from "@/components/agent-config/ToolsSection";
import { VariablesSection } from "@/components/agent-config/VariablesSection";
import { Button } from "@/components/ui/button";

import { EMPTY_AGENT, JOHN_DOE_AGENT } from "@/lib/mockAgents";
import { serializeAgent, type AgentConfig } from "@/types/agentConfig";

function isComplete(agent: AgentConfig) {
  return (
    agent.agent_id.trim().length > 0 &&
    agent.name.trim().length > 0 &&
    agent.instructions.trim().length > 0
  );
}

export function AgentConfigPage() {
  const [agent, setAgent] = useState<AgentConfig>(JOHN_DOE_AGENT);
  const [showErrors, setShowErrors] = useState(false);

  const reset = () => {
    setAgent(EMPTY_AGENT);
    setShowErrors(false);
    toast("Reset to empty.");
  };

  const loadPreset = () => {
    setAgent(JOHN_DOE_AGENT);
    setShowErrors(false);
    toast.success("Preset loaded.");
  };

  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(serializeAgent(agent), null, 2));
      toast.success("JSON copied to clipboard.");
    } catch {
      toast.error("Could not copy — your browser blocked clipboard access.");
    }
  };

  const save = () => {
    if (!isComplete(agent)) {
      setShowErrors(true);
      toast.error("Some required fields are empty.", {
        description: "Agent ID, display name, and instructions are required.",
      });
      return;
    }
    // No backend yet — surface the result in the console so the JSON shape
    // can be verified end-to-end against the orchestrator contract.
    // eslint-disable-next-line no-console
    console.info("[AgentConfig] save", serializeAgent(agent));
    toast.success("Configuration saved.");
  };

  return (
    <section className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      <header className="space-y-1">
        <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
          Configuration
        </p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Agent configuration
        </h1>
        <p className="text-sm text-muted-foreground">
          Identity, instructions, the three pluggable pipeline components,
          tools, confirmations, and variables for the conversational agent.
        </p>
      </header>

      <div className="mt-8 flex flex-col gap-6">
        <IdentitySection
          value={{ agent_id: agent.agent_id, name: agent.name }}
          onChange={(next) => setAgent({ ...agent, ...next })}
          showErrors={showErrors}
        />

        <InstructionsSection
          value={{ instructions: agent.instructions, first_message: agent.first_message }}
          onChange={(next) => setAgent({ ...agent, ...next })}
          showErrors={showErrors}
        />

        <PipelineSection
          value={{ stt: agent.stt, tts: agent.tts, llm: agent.llm }}
          onChange={(next) => setAgent({ ...agent, ...next })}
        />

        <ToolsSection
          value={agent.tools}
          onChange={(tools) => setAgent({ ...agent, tools })}
        />

        <ConfirmationsSection
          value={agent.confirmations}
          tools={agent.tools}
          onChange={(confirmations) => setAgent({ ...agent, confirmations })}
        />

        <VariablesSection
          value={agent.variables}
          onChange={(variables) => setAgent({ ...agent, variables })}
        />

        <AdvancedSection
          language={agent.language}
          vad={agent.vad}
          onLanguageChange={(language) => setAgent({ ...agent, language })}
          onVadChange={(vad) => setAgent({ ...agent, vad })}
        />

        <div className="sticky bottom-4 z-10 mt-2 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-background/90 p-3 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-background/70">
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={loadPreset} type="button">
              <FileDown data-icon="inline-start" />
              Load preset
            </Button>
            <Button variant="ghost" size="sm" onClick={reset} type="button">
              <RotateCcw data-icon="inline-start" />
              Reset
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={copyJson} type="button">
              <Copy data-icon="inline-start" />
              Copy JSON
            </Button>
            <Button size="sm" onClick={save} type="button">
              <Save data-icon="inline-start" />
              Save
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
