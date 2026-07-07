const dayMs = 1000 * 60 * 60 * 24;

function startOfDay(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

/**
 * Short relative label for a past ISO timestamp: "Today, 14:32",
 * "Yesterday, 09:05", "3d ago, 11:20", or "Mar 4" for anything a week or older.
 * Shared by the History list and the home-screen recent panel.
 */
export function formatRelativeStart(iso: string): string {
  const now = new Date();
  const then = new Date(iso);
  const diffDays = Math.round((startOfDay(now).getTime() - startOfDay(then).getTime()) / dayMs);
  const time = then.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (diffDays === 0) return `Today, ${time}`;
  if (diffDays === 1) return `Yesterday, ${time}`;
  if (diffDays > 1 && diffDays < 7) return `${diffDays}d ago, ${time}`;
  return then.toLocaleDateString([], { month: "short", day: "numeric" });
}
