import { useCallback, useEffect, useState } from "react";
import { Copy, FileDown, Loader2, RefreshCw, RotateCcw, Save } from "lucide-react";
import { toast } from "sonner";

import { AdvancedSection } from "@/components/agent-config/AdvancedSection";
import { ConfirmationsSection } from "@/components/agent-config/ConfirmationsSection";
import { IdentitySection } from "@/components/agent-config/IdentitySection";
import { InstructionsSection } from "@/components/agent-config/InstructionsSection";
import { PipelineSection } from "@/components/agent-config/PipelineSection";
import { ToolsSection } from "@/components/agent-config/ToolsSection";
import { VariablesSection } from "@/components/agent-config/VariablesSection";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import {
  listAgentConfigs,
  loadAgentConfig,
  saveAgentConfig,
  type SavedAgentConfigSummary,
} from "@/lib/agentConfigApi";
import { EMPTY_AGENT, JOHN_DOE_AGENT } from "@/lib/mockAgents";
import { cn } from "@/lib/utils";
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
  const [savedConfigs, setSavedConfigs] = useState<SavedAgentConfigSummary[]>([]);
  const [isListLoading, setIsListLoading] = useState(false);
  const [loadedConfigId, setLoadedConfigId] = useState<string | null>(null);

  // Fetch the saved-config list once on mount + expose a refresh helper.
  // Used by the "Load preset" dropdown and re-called after a successful save
  // so the newest entry appears immediately without a page reload.
  const refreshList = useCallback(async (signal?: AbortSignal) => {
    setIsListLoading(true);
    try {
      const items = await listAgentConfigs(signal);
      setSavedConfigs(items);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      const msg = err instanceof Error ? err.message : "Unknown error.";
      toast.error("Could not load saved configurations.", { description: msg });
    } finally {
      setIsListLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refreshList(controller.signal);
    return () => controller.abort();
  }, [refreshList]);

  const reset = () => {
    setAgent(EMPTY_AGENT);
    setShowErrors(false);
    setLoadedConfigId(null);
    toast("Reset to empty.");
  };

  const loadPreset = () => {
    setAgent(JOHN_DOE_AGENT);
    setShowErrors(false);
    setLoadedConfigId(null);
    toast.success("Preset loaded.");
  };

  const loadById = async (id: string) => {
    try {
      const saved = await loadAgentConfig(id);
      setAgent(saved.config as unknown as AgentConfig);
      setLoadedConfigId(saved.id);
      setShowErrors(false);
      toast.success("Configuration loaded.", {
        description: `Loaded "${saved.name}".`,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error.";
      toast.error("Could not load configuration.", { description: msg });
    }
  };

  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(serializeAgent(agent), null, 2));
      toast.success("JSON copied to clipboard.");
    } catch {
      toast.error("Could not copy — your browser blocked clipboard access.");
    }
  };

  const save = async () => {
    if (!isComplete(agent)) {
      setShowErrors(true);
      toast.error("Some required fields are empty.", {
        description: "Agent ID, display name, and instructions are required.",
      });
      return;
    }
    try {
      const saved = await saveAgentConfig(agent);
      toast.success("Configuration saved.", {
        description: `Saved as "${saved.name}".`,
      });
      // Refresh so the newly-saved row appears in the dropdown immediately.
      // Note: deliberately NOT setting loadedConfigId = saved.id — Save always
      // creates a new row (POST). Smart overwrite arrives with #52 PUT.
      void refreshList();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error.";
      toast.error("Could not save configuration.", { description: message });
    }
  };

  return (
    <section className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      <header className="space-y-1">
        <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
          Configuration
        </p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Agent configuration</h1>
        <p className="text-sm text-muted-foreground">
          Identity, instructions, the three pluggable pipeline components, tools, confirmations, and
          variables for the conversational agent.
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

        <ToolsSection value={agent.tools} onChange={(tools) => setAgent({ ...agent, tools })} />

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
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" type="button">
                  {isListLoading ? (
                    <Loader2 className="animate-spin" data-icon="inline-start" />
                  ) : (
                    <FileDown data-icon="inline-start" />
                  )}
                  Load agent
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-64">
                <DropdownMenuLabel className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
                  Built-in
                </DropdownMenuLabel>
                <DropdownMenuItem onClick={loadPreset}>John Doe — TechStore demo</DropdownMenuItem>
                {savedConfigs.length > 0 ? (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuLabel className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
                      Saved agents
                    </DropdownMenuLabel>
                    {savedConfigs.map((c) => (
                      <DropdownMenuItem
                        key={c.id}
                        onClick={() => loadById(c.id)}
                        className={cn(loadedConfigId === c.id && "bg-muted")}
                      >
                        <span className="truncate">{c.name}</span>
                      </DropdownMenuItem>
                    ))}
                  </>
                ) : null}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => {
                    void refreshList();
                  }}
                  disabled={isListLoading}
                >
                  <RefreshCw data-icon="inline-start" />
                  Refresh
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
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
