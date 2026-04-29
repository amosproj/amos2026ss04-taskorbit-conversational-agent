import { MessageSquareDashed } from "lucide-react";

import { Empty } from "@/components/Empty";

export function HistoryPage() {
  return (
    <section className="mx-auto max-w-2xl px-4 py-10 sm:px-6">
      <header className="space-y-1">
        <p className="text-sm font-medium tracking-widest text-muted-foreground uppercase">
          History
        </p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Conversation history
        </h1>
        <p className="text-sm text-muted-foreground">
          Past conversations, transcripts, and extracted data.
        </p>
      </header>

      <div className="mt-8">
        <Empty
          icon={MessageSquareDashed}
          title="History view coming up next"
          description="A list of past calls with click-into transcript and extracted data view, mirroring what the backend persists in PostgreSQL per the system architecture. Lands in the next commit."
        />
      </div>
    </section>
  );
}
