import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

type EmptyProps = {
  icon: LucideIcon;
  title: string;
  description?: string;
  className?: string;
};

/**
 * Lightweight empty / placeholder state — used while a route or feature is
 * scaffolded but not yet implemented. Matches the shadcn visual language
 * (dashed border, semantic color tokens) so the placeholder feels intentional
 * rather than broken.
 */
export function Empty({ icon: Icon, title, description, className }: EmptyProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 rounded-lg border border-dashed border-border bg-muted/30 px-6 py-12 text-center",
        className,
      )}
      role="status"
    >
      <span
        aria-hidden
        className="flex size-12 items-center justify-center rounded-full bg-background text-muted-foreground"
      >
        <Icon className="size-5" />
      </span>
      <h3 className="text-base font-medium text-foreground">{title}</h3>
      {description ? (
        <p className="max-w-sm text-sm text-muted-foreground">{description}</p>
      ) : null}
    </div>
  );
}
