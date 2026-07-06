import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import legalNotices from "@/generated/legal-notices.json";
import { cn } from "@/lib/utils";
import type { LegalNoticesFile } from "@/types/legalNotices";

const data = legalNotices as LegalNoticesFile;

function ecosystemFromPurl(purl?: string): string {
  if (!purl) return "unknown";
  if (purl.startsWith("pkg:pypi")) return "python";
  if (purl.startsWith("pkg:npm")) return "npm";
  if (purl.startsWith("pkg:gem")) return "ruby";
  if (purl.startsWith("pkg:docker")) return "docker";
  if (purl.startsWith("pkg:golang")) return "go";
  if (purl.startsWith("pkg:maven")) return "java";
  if (purl.startsWith("pkg:cargo")) return "rust";
  return "other";
}

const ECOSYSTEM_STYLES: Record<string, string> = {
  python: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  npm: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
};

export function LegalNoticesDialog() {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!search.trim()) return data.components;
    const q = search.toLowerCase();
    return data.components.filter(
      (c) => c.name.toLowerCase().includes(q) || c.license.toLowerCase().includes(q),
    );
  }, [search]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="link"
          className="h-auto p-0 text-xs text-muted-foreground hover:text-foreground"
        >
          Legal Notices
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Legal Notices</DialogTitle>
          <DialogDescription>
            Open-source licenses for third-party software used in{" "}
            {import.meta.env.VITE_APP_NAME ?? "TaskOrbit"}.
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-2">
          {/* Accessible search input: aria-label provides a readable name for screen readers */}
          <Input
            placeholder="Search by package name or license type…"
            aria-label="Search legal notices"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-9"
          />
          {/* Visible counter with live region so screen readers announce changes */}
          <span className="shrink-0 text-xs text-muted-foreground" role="status" aria-live="polite">
            {filtered.length} of {data.componentCount}
          </span>
        </div>

        <ScrollArea className="max-h-[60vh]">
          <table className="w-full text-sm">
            <thead>
              {/* Table headers: include scope="col" for proper table semantics */}
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th scope="col" className="pb-2 pr-2 font-medium">
                  Package
                </th>
                <th scope="col" className="pb-2 pr-2 font-medium">
                  Version
                </th>
                <th scope="col" className="pb-2 pr-2 font-medium">
                  License
                </th>
                <th scope="col" className="pb-2 font-medium">
                  Ecosystem
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => {
                const eco = ecosystemFromPurl(c.purl);
                return (
                  <tr key={c.purl ?? `${c.name}@${c.version}`} className="border-b last:border-0">
                    <td className="py-1.5 pr-2 font-medium">{c.name}</td>
                    <td className="py-1.5 pr-2 text-muted-foreground">{c.version}</td>
                    <td className="py-1.5 pr-2">
                      <span
                        className={cn(c.license === "UNKNOWN" && "text-muted-foreground italic")}
                        title={
                          c.license === "UNKNOWN"
                            ? "License could not be determined from the package metadata"
                            : c.license
                        }
                      >
                        {c.license}
                      </span>
                    </td>
                    <td className="py-1.5">
                      <Badge
                        variant="outline"
                        className={cn("text-[10px] leading-none", ECOSYSTEM_STYLES[eco])}
                      >
                        {eco}
                      </Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </ScrollArea>

        <p className="text-[10px] text-muted-foreground">
          Generated {data.generatedAt} · {data.componentCount} components across{" "}
          {data.scope.join(", ")}
        </p>
      </DialogContent>
    </Dialog>
  );
}
