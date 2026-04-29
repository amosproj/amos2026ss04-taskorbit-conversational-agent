import { Settings2 } from "lucide-react";

import { Empty } from "@/components/Empty";

export function AgentConfigPage() {
  return (
    <section className="mx-auto max-w-2xl px-4 py-10 sm:px-6">
      <header className="space-y-1">
        <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
          Configuration
        </p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Agent configuration
        </h1>
        <p className="text-sm text-muted-foreground">
          JSON-driven agent settings — STT, LLM, TTS, tools, and instructions.
        </p>
      </header>

      <div className="mt-8">
        <Empty
          icon={Settings2}
          title="Form coming up next"
          description="The configuration form mirrors the JSON schema shared by Meisterwerk — agent identity, the three pluggable pipeline components, tools, and variables. Lands in the next commit."
        />
      </div>
    </section>
  );
}
