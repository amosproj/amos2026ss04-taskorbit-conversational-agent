import { useCallback, useEffect, useState } from "react";
import { Bot, Copy, FileDown, Loader2, RefreshCw, RotateCcw, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { useActiveAgent } from "@/components/active-agent-provider";
import { AdvancedSection } from "@/components/agent-config/AdvancedSection";
import { PersonaGuardrailsSection } from "@/components/agent-config/PersonaGuardrailsSection";
import { ConfirmationsSection } from "@/components/agent-config/ConfirmationsSection";
import { IdentitySection } from "@/components/agent-config/IdentitySection";
import { InstructionsSection } from "@/components/agent-config/InstructionsSection";
import { PipelineSection } from "@/components/agent-config/PipelineSection";
import { ToolsSection } from "@/components/agent-config/ToolsSection";
import { VariablesSection } from "@/components/agent-config/VariablesSection";
import {
  WorkflowSection,
  type WorkflowValidationState,
} from "@/components/agent-config/WorkflowSection";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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
  deleteAgentConfig,
  listAgentConfigs,
  loadAgentConfig,
  updateAgentConfig,
  type SavedAgentConfigSummary,
} from "@/lib/agentConfigApi";
import { EMPTY_AGENT, JOHN_DOE_AGENT } from "@/lib/mockAgents";
import { cn } from "@/lib/utils";
import {
  backendToFrontendAgent,
  createUserAgent,
  customizeUserAgent,
  fetchUserAgents,
  type UserAgentEntry,
} from "@/lib/userAgentsApi";
import { serializeAgent, type AgentConfig } from "@/types/agentConfig";

function isComplete(agent: AgentConfig) {
  return (
    (agent.agent_id ?? "").trim().length > 0 &&
    (agent.name ?? "").trim().length > 0 &&
    (agent.instructions ?? "").trim().length > 0
  );
}

export function AgentConfigPage() {
  // Active agent + loadedConfigId live in shared context so the chat surface
  // sees whatever was last loaded/saved here, and the form survives route
  // navigation + page reloads (see active-agent-provider.tsx).
  const { agent, loadedConfigId, setActiveAgent } = useActiveAgent();
  // Shim so the inline JSX `setAgent({ ...agent, fieldX })` callsites below
  // don't need rewriting; loadedConfigId is preserved on every form edit.
  const setAgent = (next: AgentConfig) => setActiveAgent(next, loadedConfigId);
  const [showErrors, setShowErrors] = useState(false);
  const [savedConfigs, setSavedConfigs] = useState<SavedAgentConfigSummary[]>([]);
  const [isListLoading, setIsListLoading] = useState(false);
  const [userAgents, setUserAgents] = useState<UserAgentEntry[]>([]);
  // Tracks whether the currently-loaded agent came from /v1/user-agents.
  // Format: "ua:<db_row_id>" — the actual DB primary key, used to route
  // Save/Update to PUT /v1/user-agents/{db_row_id} for by-id updates.
  const [activeUserAgentId, setActiveUserAgentId] = useState<string | null>(
    loadedConfigId?.startsWith("ua:") ? loadedConfigId.slice(3) : null,
  );
  // true when the loaded agent is a built-in template (not a user copy).
  // Update button is hidden for built-in agents — use Save to create a copy.
  const [isLoadedBuiltIn, setIsLoadedBuiltIn] = useState(false);
  const [loadMenuOpen, setLoadMenuOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null);

  const [workflowValidation, setWorkflowValidation] = useState<WorkflowValidationState>({
    valid: true,
    error: null,
  });

  const canPersist = isComplete(agent) && workflowValidation.valid;

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
    fetchUserAgents(controller.signal)
      .then((fetched) => {
        setUserAgents(fetched);
        // isLoadedBuiltIn always starts false (unlike activeUserAgentId, which
        // parses synchronously from the persisted loadedConfigId) — correct it
        // once we know whether the restored agent is actually a customized
        // row or an untouched template, so Update doesn't wrongly show for a
        // built-in agent restored from a previous session.
        if (activeUserAgentId) {
          const entry = fetched.find((a) => a.id === activeUserAgentId);
          if (entry) setIsLoadedBuiltIn(!entry.is_customized);
        }
      })
      .catch(() => {
        /* backend unavailable — silently skip */
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshList]);

  const loadUserAgent = (entry: UserAgentEntry) => {
    const converted = backendToFrontendAgent(entry);
    // Use entry.id (DB primary key) so subsequent saves target the exact row.
    // For built-in templates entry.id === entry.template_id, so the clone path
    // still fires correctly on first save.
    const uaId = entry.id;
    setActiveAgent(converted, `ua:${uaId}`);
    setActiveUserAgentId(uaId);
    setIsLoadedBuiltIn(!entry.is_customized);
    setShowErrors(false);
    const label = entry.is_customized ? "My agent loaded." : "Built-in agent loaded.";
    toast.success(label, { description: `Loaded "${entry.name}". Edit and save to customise.` });
  };

  const reset = () => {
    setActiveAgent(EMPTY_AGENT, null);
    setActiveUserAgentId(null);
    setIsLoadedBuiltIn(false);
    setShowErrors(false);
    toast("Reset to empty.");
  };

  const loadPreset = () => {
    setActiveAgent(JOHN_DOE_AGENT, null);
    // Clear stale flags from whatever was loaded before — otherwise a prior
    // built-in load leaves Update hidden, or a stale activeUserAgentId makes
    // a later Update silently target the wrong row.
    setActiveUserAgentId(null);
    setIsLoadedBuiltIn(false);
    setShowErrors(false);
    toast.success("Preset loaded.");
  };

  const loadById = async (id: string) => {
    try {
      const saved = await loadAgentConfig(id);
      // The backend stores configs in its own shape (persona/greeting/etc.),
      // not the frontend AgentConfig shape — same conversion as loadUserAgent.
      const normalized = backendToFrontendAgent({
        id: saved.id,
        template_id: null,
        name: saved.name,
        config: saved.config as unknown as UserAgentEntry["config"],
        is_default: false,
        is_customized: true,
      });
      setActiveAgent(normalized, saved.id);
      // Same reasoning as loadPreset — this legacy path is a different row
      // than whatever was loaded before, so stale flags must not carry over.
      setActiveUserAgentId(null);
      setIsLoadedBuiltIn(false);
      setShowErrors(false);
      toast.success("Configuration loaded.", {
        description: `Loaded "${saved.name}".`,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error.";
      toast.error("Could not load configuration.", { description: msg });
    }
  };

  const handleDelete = (e: React.MouseEvent, id: string, name: string) => {
    e.stopPropagation();
    // Close the Load agent dropdown first, then open the dialog on the next tick.
    // If the dialog opens while the DropdownMenu is still mounted/focused, Radix's
    // focus management conflicts and leaves the dropdown in a broken state after close.
    setLoadMenuOpen(false);
    setPendingDelete({ id, name });
    setTimeout(() => setDeleteDialogOpen(true), 0);
  };

  const confirmDelete = async (target: { id: string; name: string }) => {
    try {
      await deleteAgentConfig(target.id);
      toast.success(`"${target.name}" deleted.`);
      // Always refresh — a stale list here keeps the deleted agent showing
      // up in the Workflow dropdowns and can falsely trip the duplicate
      // agent_id check, not just when you delete the agent you have open.
      const fresh = await fetchUserAgents();
      setUserAgents(fresh);
      if (loadedConfigId === target.id) {
        const defaultEntry = fresh.find((a) => a.is_default) ?? fresh[0];
        if (defaultEntry) {
          loadUserAgent(defaultEntry);
        } else {
          setActiveAgent(JOHN_DOE_AGENT, null);
          setActiveUserAgentId(null);
          setIsLoadedBuiltIn(false);
        }
      }
      void refreshList();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error.";
      toast.error("Could not delete configuration.", { description: msg });
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
    if (!workflowValidation.valid) {
      toast.error("Fix workflow errors before saving.", {
        description: workflowValidation.error ?? "Invalid workflow configuration.",
      });
      return;
    }
    // Always POST to create a fresh row — never touch whatever agent is
    // currently loaded. This is the "Save as new" contract: activeUserAgentId
    // is intentionally ignored here so Step C is not overwritten when the user
    // fills in Step B and clicks "Save as new".
    try {
      const saved = await createUserAgent(agent);
      setActiveAgent(backendToFrontendAgent(saved), `ua:${saved.id}`);
      setActiveUserAgentId(saved.id);
      setIsLoadedBuiltIn(false);
      toast.success("Agent saved.", { description: `Saved "${saved.name}".` });
      const updated = await fetchUserAgents();
      setUserAgents(updated);
      void refreshList();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error.";
      toast.error("Could not save agent.", { description: message });
    }
  };

  const update = async () => {
    if (!loadedConfigId) return;
    if (!isComplete(agent)) {
      setShowErrors(true);
      toast.error("Some required fields are empty.");
      return;
    }
    if (!workflowValidation.valid) {
      toast.error("Fix workflow errors before updating.", {
        description: workflowValidation.error ?? "Invalid workflow configuration.",
      });
      return;
    }
    // User agent update — copy-on-write via /v1/user-agents.
    if (activeUserAgentId) {
      try {
        const saved = await customizeUserAgent(activeUserAgentId, agent);
        setActiveAgent(backendToFrontendAgent(saved), `ua:${activeUserAgentId}`);
        toast.success("Agent updated.", { description: `Updated "${saved.name}".` });
        const updated = await fetchUserAgents();
        setUserAgents(updated);
        void refreshList();
      } catch (err) {
        const message = err instanceof Error ? err.message : "Unknown error.";
        toast.error("Could not update agent.", { description: message });
      }
      return;
    }
    try {
      const saved = await updateAgentConfig(loadedConfigId, agent);
      toast.success("Configuration updated.", {
        description: `Updated "${saved.name}".`,
      });
      void refreshList();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error.";
      toast.error("Could not update configuration.", { description: message });
    }
  };

  return (
    <section className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
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

        <PersonaGuardrailsSection
          value={agent.persona_constraints}
          onChange={(persona_constraints) => setAgent({ ...agent, persona_constraints })}
        />

        <PipelineSection
          value={{ stt: agent.stt, tts: agent.tts, llm: agent.llm }}
          onChange={(next) => setAgent({ ...agent, ...next })}
        />

        <ToolsSection value={agent.tools} onChange={(tools) => setAgent({ ...agent, tools })} />

        <WorkflowSection
          currentAgentId={agent.agent_id}
          userAgentEntries={userAgents}
          workflowDependencies={agent.workflow_dependencies}
          workflowRules={agent.workflow_rules}
          allowedHandoffs={agent.allowed_handoffs}
          onWorkflowDependenciesChange={(workflow_dependencies) =>
            setAgent({ ...agent, workflow_dependencies })
          }
          onWorkflowRulesChange={(workflow_rules) => setAgent({ ...agent, workflow_rules })}
          onAllowedHandoffsChange={(allowed_handoffs) => setAgent({ ...agent, allowed_handoffs })}
          onValidationChange={setWorkflowValidation}
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
          contextLimit={agent.context_limit}
          onLanguageChange={(language) => setAgent({ ...agent, language })}
          onVadChange={(vad) => setAgent({ ...agent, vad })}
          onContextLimitChange={(context_limit) => setAgent({ ...agent, context_limit })}
        />

        <div className="sticky bottom-4 z-10 mt-2 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-background/90 p-3 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-background/70">
          <div className="flex flex-wrap items-center gap-2">
            <DropdownMenu open={loadMenuOpen} onOpenChange={setLoadMenuOpen}>
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
                {/* Built-in agents — unmodified templates (is_customized=false) */}
                {userAgents.filter((e) => !e.is_customized).length > 0 ? (
                  <>
                    <DropdownMenuLabel className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
                      Built-in agents
                    </DropdownMenuLabel>
                    {userAgents
                      .filter((e) => !e.is_customized)
                      .map((entry) => (
                        <DropdownMenuItem
                          key={entry.id}
                          onClick={() => loadUserAgent(entry)}
                          className={cn(
                            "flex items-center gap-2",
                            activeUserAgentId === entry.id && "bg-muted",
                          )}
                        >
                          <Bot className="h-3 w-3 shrink-0 text-muted-foreground" />
                          <span className="truncate">{entry.name}</span>
                        </DropdownMenuItem>
                      ))}
                    <DropdownMenuSeparator />
                  </>
                ) : null}
                <DropdownMenuLabel className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
                  Demo
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
                        className={cn(
                          "group flex items-center justify-between",
                          loadedConfigId === c.id && "bg-muted",
                        )}
                      >
                        <span className="truncate">{c.name}</span>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 opacity-0 group-hover:opacity-100 hover:text-destructive"
                          onClick={(e) => handleDelete(e, c.id, c.name)}
                        >
                          <Trash2 className="h-3 w-3" />
                          <span className="sr-only">Delete</span>
                        </Button>
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
            {loadedConfigId && !isLoadedBuiltIn ? (
              <Button size="sm" onClick={update} type="button" disabled={!canPersist}>
                <Save data-icon="inline-start" />
                Update
              </Button>
            ) : null}
            <Button
              size="sm"
              onClick={save}
              variant={loadedConfigId ? "outline" : "default"}
              type="button"
              disabled={!canPersist}
            >
              <Save data-icon="inline-start" />
              {loadedConfigId ? "Save as new" : "Save"}
            </Button>
          </div>
        </div>
      </div>
      <AlertDialog
        open={deleteDialogOpen}
        onOpenChange={(open) => {
          setDeleteDialogOpen(open);
          if (!open) setPendingDelete(null);
        }}
      >
        <AlertDialogContent onCloseAutoFocus={(e) => e.preventDefault()}>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete agent configuration?</AlertDialogTitle>
            <AlertDialogDescription>
              <strong>&ldquo;{pendingDelete?.name}&rdquo;</strong> will be permanently deleted. This
              cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingDelete) void confirmDelete(pendingDelete);
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
